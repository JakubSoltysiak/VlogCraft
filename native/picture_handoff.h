#pragma once

#include "media.h"
#include "picture_handoff_trace.h"
#include <d3d11_4.h>
#include <dxgi1_2.h>
#include <wrl/client.h>
#include <array>
#include <exception>
#include <memory>
#include <mutex>

// One producer and one consumer, each using its own immediate context. Generation
// changes and cancellation may come from another thread. The metadata mutex is
// never held across FFmpeg or D3D calls.
class PictureHandoff {
public:
    static constexpr int slotCount = 2;
    enum class State {
        Free, CopySubmitting, CopyPending, Ready, DiscardReady, Acquiring,
        ConsumerHeld, ConsumerPending, Recycling
    };

    struct Picture {
        int slot = -1;
        uint64_t generation = 0, serial = 0;
        int64_t pts = AV_NOPTS_VALUE;
        int width = 0, height = 0;
        ID3D11Texture2D* texture = nullptr;
        ID3D11ShaderResourceView* luma = nullptr;
        ID3D11ShaderResourceView* chroma = nullptr;
        explicit operator bool() const { return slot >= 0; }
    };

    struct SlotSnapshot {
        State state = State::Free;
        uint64_t generation = 0, serial = 0;
        UINT64 fencePoint = 0;
        int64_t pts = AV_NOPTS_VALUE;
        std::weak_ptr<AVFrame> sourceIdentity;
        bool retained = false, gpuCopyValid = false;
        double copyCpuMs = 0, gpuCopyMs = 0;
        unsigned copyPendingPolls = 0, consumerPendingPolls = 0;
        Clock::time_point submitted{}, copyCompleted{}, published{}, acquired{};
        Clock::time_point consumerSubmitted{}, consumerCompleted{}, reusable{};
        Clock::time_point lastCopyPending{}, lastConsumerPending{};
    };

    struct Snapshot {
        std::array<SlotSnapshot, slotCount> slots{};
        uint64_t generation = 0, submissions = 0, publications = 0, acquisitions = 0;
        uint64_t completions = 0, discarded = 0, backpressure = 0, keyTimeouts = 0;
        unsigned retained = 0, peakRetained = 0, peakSlots = 0;
        bool cancelled = false, failed = false;
    };

    PictureHandoff(AVD3D11VADeviceContext* producer, ID3D11Device* consumer,
                   const AVFrame* prototype, uint64_t generation = 1, bool preferFence = false,
                   PictureHandoffTrace* trace = nullptr, int lane = -1)
        : producer_(producer), consumer_(consumer), trace_(trace),
          traceRing_(trace ? trace->openRing() : 0), traceLane_(lane) {
        const auto* frames = sourceFrames(prototype);
        if (!producer_ || !consumer_ || !frames || !producer_->device ||
            frames->device_ctx->hwctx != producer_ || !producer_->device_context ||
            !producer_->lock || !producer_->unlock)
            throw std::runtime_error("handoff requires a D3D11VA frame and its initialized producer");
        producerRef_.reset(av_buffer_ref(frames->device_ref));
        if (!producerRef_) throw std::bad_alloc();
        const auto producerAdapter = adapterLuid(producer_->device);
        const auto consumerAdapter = adapterLuid(consumer);
        if (producer_->device == consumer || producerAdapter.LowPart != consumerAdapter.LowPart ||
            producerAdapter.HighPart != consumerAdapter.HighPart)
            throw std::runtime_error("handoff requires a distinct device on the producer adapter");

        sourceTexture(prototype)->GetDesc(&desc_);
        if (!compatible(prototype, desc_))
            throw std::runtime_error("unsupported handoff decoder texture");

        desc_.ArraySize = 1;
        desc_.BindFlags = D3D11_BIND_SHADER_RESOURCE;
        desc_.MiscFlags = D3D11_RESOURCE_MISC_SHARED_NTHANDLE | D3D11_RESOURCE_MISC_SHARED_KEYEDMUTEX;
        desc_.CPUAccessFlags = 0;
        width_ = prototype->width;
        height_ = prototype->height;
        state_.generation = generation;
        checkSharing(producer_->device);
        checkSharing(consumer);
        consumer->GetImmediateContext(&consumerContext_);
        Microsoft::WRL::ComPtr<ID3D11Device1> consumer1;
        check(consumer_.As(&consumer1), "handoff consumer device1");
        if (preferFence) {
            Microsoft::WRL::ComPtr<ID3D11Device5> device5;
            if (SUCCEEDED(producer_->device->QueryInterface(IID_PPV_ARGS(&device5))) &&
                SUCCEEDED(device5->CreateFence(0,D3D11_FENCE_FLAG_NONE,IID_PPV_ARGS(&copyFence_)))) {
                if (FAILED(producer_->device_context->QueryInterface(IID_PPV_ARGS(&signalContext_))))
                    copyFence_.Reset();
            }
        }
        for (auto& slot : slots_) createSlot(slot, consumer1.Get());
    }

    // Destroy only after both endpoints have stopped. A live GPU operation
    // keeps its frame pinned even if normal teardown failed.
    ~PictureHandoff() {
        if (idle()) return;
        try {
            if (drain(std::chrono::seconds(5))) return;
        } catch (...) {}
        std::terminate();
    }
    PictureHandoff(const PictureHandoff&) = delete;
    PictureHandoff& operator=(const PictureHandoff&) = delete;

    const D3D11_TEXTURE2D_DESC& descriptor() const { return desc_; }
    // Per image. Texture dimensions do not tell us the driver's allocation size.
    uint64_t visiblePayloadBytes() const { return payloadBytes(width_, height_); }
    uint64_t storagePayloadBytes() const { return payloadBytes(desc_.Width, desc_.Height); }

    bool usingFence() const { return bool(copyFence_) && !signalFailed_.load(); }

    void traceSelection(const char* event, int64_t sequence, int64_t transport, const AVFrame* frame) const {
        if (trace_) trace_->add(event,traceRing_,traceLane_,transport,sequence,-1,0,frame);
    }

    Snapshot snapshot() const {
        std::lock_guard<std::mutex> lock(mutex_);
        return state_;
    }

    State slotState(int index) const {
        std::lock_guard<std::mutex> lock(mutex_);
        return state_.slots.at(index).state;
    }

    bool idle() const {
        std::lock_guard<std::mutex> lock(mutex_);
        for (const auto& slot : state_.slots)
            if (slot.state != State::Free) return false;
        return true;
    }

    void setGeneration(uint64_t generation) {
        std::lock_guard<std::mutex> lock(mutex_);
        if (generation < state_.generation) throw std::invalid_argument("handoff generation regressed");
        state_.generation = generation;
        discardStaleReady();
    }

    void cancel() {
        std::lock_guard<std::mutex> lock(mutex_);
        state_.cancelled = true;
        discardStaleReady();
    }

    // No capacity wait and no GPU-completion wait. The producer still takes
    // FFmpeg's recursive lock to use the immediate context.
    int trySubmit(const AVFrame* frame, uint64_t generation) {
        return trySubmit(frame, generation, {}, []{return true;});
    }

    template<class StillWanted>
    int trySubmit(const AVFrame* frame, uint64_t generation,
                  const std::weak_ptr<AVFrame>& sourceIdentity, StillWanted&& stillWanted) {
        {
            std::lock_guard<std::mutex> lock(mutex_);
            if (!current(generation)) return -1;
        }
        auto* texture = validatedTexture(frame);
        const UINT slice = static_cast<UINT>(reinterpret_cast<intptr_t>(frame->data[1]));
        int index;
        uint64_t serial;
        {
            std::lock_guard<std::mutex> lock(mutex_);
            if (!current(generation)) return -1;
            index = reserve(frame, generation, sourceIdentity);
            if (index < 0) return -1;
            serial = state_.slots[index].serial;
        }
        auto& slot = slots_[index];
        const int ref = av_frame_ref(slot.source.get(), frame);
        if (ref < 0) {
            recycle(index);
            avcheck(ref, "retain handoff source");
        }
        {
            std::lock_guard<std::mutex> lock(mutex_);
            state_.slots[index].retained = true;
            ++state_.retained;
            state_.peakRetained = (std::max)(state_.peakRetained, state_.retained);
        }

        HRESULT acquired = S_FALSE;
        double cpuMs = 0;
        UINT64 fencePoint = 0;
        Clock::time_point submitted{};
        auto traceSubmission = [&](const char* step, int64_t value = 0) {
            if (trace_) trace_->add(step,traceRing_,traceLane_,generation,-1,index,serial,nullptr,value);
        };
        {
            traceSubmission("producer_lock_begin");
            ProducerLock lock(producer_);
            traceSubmission("producer_lock_return");
            if (active(generation) && stillWanted()) {
                acquired = slot.producerKey->AcquireSync(producerKey, 0);
                if (acquired == S_OK) {
                    auto* context = producer_->device_context;
                    context->Begin(slot.copyDisjoint.Get());
                    context->End(slot.copyBegin.Get());
                    const auto began = Clock::now();
                    context->CopySubresourceRegion(slot.local.Get(), 0, 0, 0, 0, texture, slice, nullptr);
                    traceSubmission("copy_issued");
                    cpuMs = seconds(began) * 1000;
                    context->End(slot.copyEnd.Get());
                    context->End(slot.copyDisjoint.Get());
                    context->End(slot.copyEvent.Get());
                    if (usingFence()) {
                        const UINT64 point = ++nextPoint_;
                        if (SUCCEEDED(signalContext_->Signal(copyFence_.Get(),point))) fencePoint = point;
                        else signalFailed_.store(true);
                    }
                    // Transfer the key on the serialized producer context.
                    // The consumer cannot acquire this slot until CPU-side
                    // fence observation separately publishes Ready.
                    slot.keyReleaseResult = fencePoint ? slot.producerKey->ReleaseSync(consumerKey) : S_OK;
                    traceSubmission("producer_key_release",slot.keyReleaseResult);
                    context->Flush();
                    submitted = Clock::now();
                }
            }
        }
        if (acquired != S_OK) {
            traceSubmission("copy_abort",acquired);
            if (acquired != WAIT_TIMEOUT && acquired != S_FALSE) {
                markFailed();
                recycle(index);
                throwStatus(acquired, "handoff producer key acquisition");
            }
            recycle(index);
            if (acquired == WAIT_TIMEOUT) recordKeyTimeout();
            return -1;
        }
        {
            std::lock_guard<std::mutex> lock(mutex_);
            auto& status = state_.slots[index];
            status.copyCpuMs = cpuMs;
            status.fencePoint = fencePoint;
            status.submitted = submitted;
            status.state = State::CopyPending;
            traceSlot("copy_pending",index,fencePoint);
            ++state_.submissions;
            nextSlot_ = (index + 1) % slotCount;
        }
        return index;
    }

    // Use pollFencedProducer and pollProducerQueries on separate endpoints when
    // needed. Each path has a single observer and handles disjoint slots.
    int pollProducer() {
        const int fenced = pollFencedProducer();
        return fenced + pollProducerQueries();
    }

    int pollFencedProducer() {
        if (!copyFence_) return 0;
        int count = 0;
        const auto done = copyFence_->GetCompletedValue();
        for (int i = 0; i < slotCount; ++i) {
            UINT64 point;
            {
                std::lock_guard<std::mutex> lock(mutex_);
                const auto& status = state_.slots[i];
                if (status.state != State::CopyPending || !status.fencePoint) continue;
                point = status.fencePoint;
            }
            // Signal and key release were enqueued on the producer context.
            // Their observation can progress while it is busy submitting a peer slot.
            const HRESULT ready = done == UINT64_MAX ? DXGI_ERROR_DEVICE_REMOVED :
                                  done >= point ? S_OK : S_FALSE;
            count += observeCopy(i, ready, slots_[i].keyReleaseResult);
        }
        return count;
    }

    int pollProducerQueries() {
        int count = 0;
        for (int i = 0; i < slotCount; ++i) {
            {
                std::lock_guard<std::mutex> lock(mutex_);
                const auto& status = state_.slots[i];
                if (status.state != State::CopyPending || status.fencePoint) continue;
            }
            auto& slot = slots_[i];
            HRESULT ready, released = S_OK;
            double gpuMs = 0;
            bool gpuValid = false;
            {
                ProducerLock lock(producer_);
                auto* context = producer_->device_context;
                ready = eventStatus(context, slot.copyEvent.Get());
                if (ready == S_OK) {
                    gpuValid = copyDuration(context, slot, gpuMs);
                    released = slot.producerKey->ReleaseSync(consumerKey);
                }
            }
            count += observeCopy(i, ready, released, gpuValid, gpuMs);
        }
        return count;
    }

    // The consumer can return an image that was never sampled without
    // queuing a consumer completion event.
    void discardReady(uint64_t generation, int index) {
        std::lock_guard<std::mutex> lock(mutex_);
        auto& status = state_.slots.at(index);
        if (status.state == State::Ready && status.generation == generation) {
            status.state = State::DiscardReady;
            traceSlot("discard_ready",index);
        }
    }

    // Requesting a specific slot never queues a consumer dependency for an
    // unready picture. With no slot specified, return the oldest ready picture.
    Picture tryAcquire(uint64_t generation, int requestedSlot = -1) {
        int index = -1;
        {
            std::lock_guard<std::mutex> lock(mutex_);
            if (!current(generation)) return {};
            for (int i = 0; i < slotCount; ++i) {
                const auto& status = state_.slots[i];
                if (requestedSlot >= 0 && i != requestedSlot) continue;
                if (status.state == State::Ready && status.generation == generation &&
                    (index < 0 || status.serial < state_.slots[index].serial)) index = i;
            }
            if (index < 0) return {};
            state_.slots[index].state = State::Acquiring;
        }
        if (!takeConsumerKey(index)) return {};
        {
            std::lock_guard<std::mutex> lock(mutex_);
            auto& status = state_.slots[index];
            if (current(status.generation)) {
                status.state = State::ConsumerHeld;
                status.acquired = Clock::now();
                ++state_.acquisitions;
                traceSlot("acquire",index);
                return picture(index);
            }
        }
        returnToProducer(index, true);
        return {};
    }

    // End and flush on the consumer's immediate context after its last use of
    // the slot. The lease must no longer be used by the caller after this.
    void finish(const Picture& lease) {
        {
            std::lock_guard<std::mutex> lock(mutex_);
            const auto& status = state_.slots.at(lease.slot);
            if (status.state != State::ConsumerHeld || status.serial != lease.serial ||
                status.generation != lease.generation)
                throw std::logic_error("invalid handoff consumer lease");
        }
        consumerContext_->End(slots_[lease.slot].consumerEvent.Get());
        consumerContext_->Flush();
        const auto submitted = Clock::now();
        std::lock_guard<std::mutex> lock(mutex_);
        auto& status = state_.slots[lease.slot];
        status.consumerSubmitted = submitted;
        status.state = State::ConsumerPending;
        traceSlot("consumer_pending",lease.slot);
    }

    int pollConsumer() {
        int count = 0;
        for (int i = 0; i < slotCount; ++i) {
            const State state = slotState(i);
            if (state == State::DiscardReady) {
                if (!takeConsumerKey(i, true)) continue;
                returnToProducer(i, true);
                ++count;
            } else if (state == State::ConsumerPending) {
                const HRESULT ready = eventStatus(consumerContext_.Get(), slots_[i].consumerEvent.Get());
                if (ready == S_FALSE) {
                    recordPending(i, false);
                    continue;
                }
                if (ready != S_OK) {
                    recoverQuery(i, consumer_.Get(), ready, "handoff consumer completion query");
                    continue;
                }
                {
                    std::lock_guard<std::mutex> lock(mutex_);
                    state_.slots[i].consumerCompleted = Clock::now();
                    ++state_.completions;
                }
                returnToProducer(i, false);
                ++count;
            }
        }
        return count;
    }

    // Call only after the endpoints are quiescent. Close any lease left by a
    // stopped consumer and poll both endpoints with the original lock intact.
    bool drain(std::chrono::milliseconds timeout) {
        cancel();
        const auto deadline = Clock::now() + timeout;
        for (int i = 0; i < slotCount; ++i) {
            if (slotState(i) == State::ConsumerHeld) finish(picture(i));
        }
        do {
            pollProducer();
            pollConsumer();
            if (idle()) return true;
            if (Clock::now() >= deadline) break;
            Sleep(1);
        } while (Clock::now() < deadline);
        return false;
    }

private:
    static constexpr UINT64 producerKey = 0, consumerKey = 1;
    static constexpr UINT queryFlags = D3D11_ASYNC_GETDATA_DONOTFLUSH;
    template <class T> using ComPtr = Microsoft::WRL::ComPtr<T>;

    struct FrameFree {
        void operator()(AVFrame* frame) const { av_frame_free(&frame); }
    };
    struct BufferFree {
        void operator()(AVBufferRef* ref) const { av_buffer_unref(&ref); }
    };
    struct SharedHandle {
        HANDLE handle = nullptr;
        ~SharedHandle() { if (handle) CloseHandle(handle); }
    };
    struct ProducerLock {
        AVD3D11VADeviceContext* context;
        explicit ProducerLock(AVD3D11VADeviceContext* hw) : context(hw) { hw->lock(hw->lock_ctx); }
        ~ProducerLock() { context->unlock(context->lock_ctx); }
    };
    struct Slot {
        HRESULT keyReleaseResult = S_OK;
        ComPtr<ID3D11Texture2D> local, opened;
        ComPtr<IDXGIKeyedMutex> producerKey, consumerKey;
        ComPtr<ID3D11ShaderResourceView> luma, chroma;
        ComPtr<ID3D11Query> copyEvent, copyDisjoint, copyBegin, copyEnd, consumerEvent;
        std::unique_ptr<AVFrame, FrameFree> source;
    };

    AVD3D11VADeviceContext* producer_;
    std::unique_ptr<AVBufferRef, BufferFree> producerRef_;
    ComPtr<ID3D11Device> consumer_;
    ComPtr<ID3D11DeviceContext> consumerContext_;
    D3D11_TEXTURE2D_DESC desc_{};
    int width_ = 0, height_ = 0, nextSlot_ = 0;
    ComPtr<ID3D11Fence> copyFence_;
    ComPtr<ID3D11DeviceContext4> signalContext_;
    std::atomic<bool> signalFailed_{false};
    UINT64 nextPoint_ = 0;
    uint64_t serial_ = 0;
    std::array<Slot, slotCount> slots_;
    mutable std::mutex mutex_;
    Snapshot state_;
    PictureHandoffTrace* trace_;
    int traceRing_, traceLane_;

    // Caller holds the metadata mutex.
    void traceSlot(const char* event, int index, int64_t value = 0) {
        if (!trace_) return;
        const auto& status = state_.slots[index];
        trace_->add(event,traceRing_,traceLane_,status.generation,-1,index,status.serial,nullptr,value);
    }

    static const AVHWFramesContext* sourceFrames(const AVFrame* frame) {
        if (!frame || frame->format != AV_PIX_FMT_D3D11 || !frame->hw_frames_ctx ||
            !frame->data[0] || !frame->buf[0])
            return nullptr;
        const auto* frames = reinterpret_cast<const AVHWFramesContext*>(frame->hw_frames_ctx->data);
        return frames && frames->device_ctx && frames->device_ref ? frames : nullptr;
    }

    static ID3D11Texture2D* sourceTexture(const AVFrame* frame) {
        return reinterpret_cast<ID3D11Texture2D*>(frame->data[0]);
    }

    static LUID adapterLuid(ID3D11Device* device) {
        ComPtr<IDXGIDevice> dxgi;
        ComPtr<IDXGIAdapter> adapter;
        DXGI_ADAPTER_DESC adapterDesc{};
        check(device->QueryInterface(IID_PPV_ARGS(&dxgi)), "handoff DXGI device");
        check(dxgi->GetAdapter(&adapter), "handoff DXGI adapter");
        check(adapter->GetDesc(&adapterDesc), "handoff DXGI adapter description");
        return adapterDesc.AdapterLuid;
    }

    static bool compatible(const AVFrame* frame, const D3D11_TEXTURE2D_DESC& desc) {
        constexpr UINT sharing = D3D11_RESOURCE_MISC_SHARED | D3D11_RESOURCE_MISC_SHARED_KEYEDMUTEX |
            D3D11_RESOURCE_MISC_SHARED_NTHANDLE;
        const auto slice = reinterpret_cast<intptr_t>(frame->data[1]);
        return desc.Usage == D3D11_USAGE_DEFAULT && (desc.BindFlags & D3D11_BIND_DECODER) &&
            !(desc.MiscFlags & sharing) && !desc.CPUAccessFlags && desc.MipLevels == 1 &&
            desc.SampleDesc.Count == 1 && !desc.SampleDesc.Quality &&
            (desc.Format == DXGI_FORMAT_NV12 || desc.Format == DXGI_FORMAT_P010) &&
            desc.Width % 2 == 0 && desc.Height % 2 == 0 && slice >= 0 && uint64_t(slice) < desc.ArraySize &&
            frame->width > 0 && frame->height > 0 && frame->width % 2 == 0 && frame->height % 2 == 0 &&
            UINT(frame->width) <= desc.Width && UINT(frame->height) <= desc.Height;
    }

    ID3D11Texture2D* validatedTexture(const AVFrame* frame) const {
        const auto* frames = sourceFrames(frame);
        if (!frames || frames->device_ctx->hwctx != producer_)
            throw std::runtime_error("handoff frame is not from the producer");
        auto* texture = sourceTexture(frame);
        D3D11_TEXTURE2D_DESC source{};
        texture->GetDesc(&source);
        if (!compatible(frame, source) || source.Format != desc_.Format ||
            source.Width != desc_.Width || source.Height != desc_.Height ||
            frame->width != width_ || frame->height != height_)
            throw std::runtime_error("handoff picture format or size changed");
        return texture;
    }

    uint64_t payloadBytes(UINT width, UINT height) const {
        return uint64_t(width) * height * 3 / (desc_.Format == DXGI_FORMAT_P010 ? 1 : 2);
    }

    void checkSharing(ID3D11Device* device) const {
        D3D11_FEATURE_DATA_D3D11_OPTIONS options{};
        check(device->CheckFeatureSupport(D3D11_FEATURE_D3D11_OPTIONS, &options, sizeof(options)),
              "handoff sharing features");
        UINT support = 0;
        check(device->CheckFormatSupport(desc_.Format, &support), "handoff planar format support");
        if (!options.ExtendedResourceSharing || !(support & D3D11_FORMAT_SUPPORT_TEXTURE2D))
            throw std::runtime_error("handoff planar sharing unavailable");
    }

    void createSlot(Slot& slot, ID3D11Device1* consumer1) {
        slot.source.reset(av_frame_alloc());
        if (!slot.source) throw std::bad_alloc();
        check(producer_->device->CreateTexture2D(&desc_, nullptr, &slot.local), "handoff single-image texture");
        check(slot.local.As(&slot.producerKey), "handoff producer keyed mutex");
        {
            ComPtr<IDXGIResource1> resource;
            check(slot.local.As(&resource), "handoff shared resource");
            SharedHandle handle;
            check(resource->CreateSharedHandle(nullptr, DXGI_SHARED_RESOURCE_READ | DXGI_SHARED_RESOURCE_WRITE,
                  nullptr, &handle.handle), "handoff create NT handle");
            check(consumer1->OpenSharedResource1(handle.handle, IID_PPV_ARGS(&slot.opened)),
                  "handoff open NT handle");
        }
        check(slot.opened.As(&slot.consumerKey), "handoff consumer keyed mutex");
        const bool ten = desc_.Format == DXGI_FORMAT_P010;
        D3D11_SHADER_RESOURCE_VIEW_DESC view{};
        view.ViewDimension = D3D11_SRV_DIMENSION_TEXTURE2DARRAY;
        view.Texture2DArray.MipLevels = view.Texture2DArray.ArraySize = 1;
        view.Format = ten ? DXGI_FORMAT_R16_UNORM : DXGI_FORMAT_R8_UNORM;
        check(consumer_->CreateShaderResourceView(slot.opened.Get(), &view, &slot.luma), "handoff luma view");
        view.Format = ten ? DXGI_FORMAT_R16G16_UNORM : DXGI_FORMAT_R8G8_UNORM;
        check(consumer_->CreateShaderResourceView(slot.opened.Get(), &view, &slot.chroma), "handoff chroma view");
        createQuery(producer_->device, D3D11_QUERY_EVENT, slot.copyEvent);
        createQuery(producer_->device, D3D11_QUERY_TIMESTAMP_DISJOINT, slot.copyDisjoint);
        createQuery(producer_->device, D3D11_QUERY_TIMESTAMP, slot.copyBegin);
        createQuery(producer_->device, D3D11_QUERY_TIMESTAMP, slot.copyEnd);
        createQuery(consumer_.Get(), D3D11_QUERY_EVENT, slot.consumerEvent);
    }

    static void createQuery(ID3D11Device* device, D3D11_QUERY kind, ComPtr<ID3D11Query>& query) {
        const D3D11_QUERY_DESC desc{kind, 0};
        check(device->CreateQuery(&desc, &query), "handoff GPU query");
    }

    static HRESULT eventStatus(ID3D11DeviceContext* context, ID3D11Query* query) {
        BOOL complete = FALSE;
        const HRESULT result = context->GetData(query, &complete, sizeof(complete), queryFlags);
        if (result == S_OK && !complete) return E_UNEXPECTED;
        return result;
    }

    static bool copyDuration(ID3D11DeviceContext* context, const Slot& slot, double& ms) {
        D3D11_QUERY_DATA_TIMESTAMP_DISJOINT disjoint{};
        UINT64 begin = 0, end = 0;
        if (context->GetData(slot.copyDisjoint.Get(), &disjoint, sizeof(disjoint), queryFlags) != S_OK ||
            context->GetData(slot.copyBegin.Get(), &begin, sizeof(begin), queryFlags) != S_OK ||
            context->GetData(slot.copyEnd.Get(), &end, sizeof(end), queryFlags) != S_OK ||
            disjoint.Disjoint || !disjoint.Frequency || end < begin) return false;
        ms = 1000.0 * (end - begin) / disjoint.Frequency;
        return true;
    }

    // Caller holds the metadata mutex.
    bool current(uint64_t generation) const {
        return !state_.cancelled && !state_.failed && state_.generation == generation;
    }

    bool active(uint64_t generation) const {
        std::lock_guard<std::mutex> lock(mutex_);
        return current(generation);
    }

    void discardStaleReady() {
        for (int i = 0; i < slotCount; ++i) {
            auto& status = state_.slots[i];
            if (status.state == State::Ready && !current(status.generation)) {
                status.state = State::DiscardReady;
                traceSlot("discard_stale",i);
            }
        }
    }

    int reserve(const AVFrame* frame, uint64_t generation, const std::weak_ptr<AVFrame>& sourceIdentity) {
        for (int offset = 0; offset < slotCount; ++offset) {
            const int i = (nextSlot_ + offset) % slotCount;
            auto& status = state_.slots[i];
            if (status.state != State::Free) continue;
            status = {};
            status.state = State::CopySubmitting;
            status.generation = generation;
            status.serial = ++serial_;
            status.pts = frame->best_effort_timestamp;
            status.sourceIdentity = sourceIdentity;
            if (trace_) trace_->add("reserve",traceRing_,traceLane_,generation,-1,i,status.serial,frame);
            unsigned inUse = 0;
            for (const auto& entry : state_.slots) inUse += entry.state != State::Free;
            state_.peakSlots = (std::max)(state_.peakSlots, inUse);
            return i;
        }
        ++state_.backpressure;
        return -1;
    }

    Picture picture(int index) const {
        const auto& status = state_.slots[index];
        const auto& slot = slots_[index];
        return {index, status.generation, status.serial, status.pts, width_, height_, slot.opened.Get(),
                slot.luma.Get(), slot.chroma.Get()};
    }

    void recordPending(int index, bool copy) {
        std::lock_guard<std::mutex> lock(mutex_);
        auto& status = state_.slots[index];
        if (copy) {
            ++status.copyPendingPolls;
            status.lastCopyPending = Clock::now();
        } else {
            ++status.consumerPendingPolls;
            status.lastConsumerPending = Clock::now();
        }
    }

    bool observeCopy(int index, HRESULT ready, HRESULT released, bool gpuValid = false, double gpuMs = 0) {
        if (ready == S_FALSE) {
            recordPending(index, true);
            return false;
        }
        if (ready != S_OK) {
            recoverQuery(index, producer_->device, ready, "handoff producer completion query");
            return false;
        }
        const auto complete = Clock::now();
        if (released != S_OK) {
            markFailed();
            recycle(index);
            throwStatus(released, "handoff producer key release");
        }
        std::lock_guard<std::mutex> lock(mutex_);
        auto& status = state_.slots[index];
        status.copyCompleted = complete;
        status.gpuCopyValid = gpuValid;
        status.gpuCopyMs = gpuMs;
        if (current(status.generation)) {
            status.published = Clock::now();
            status.state = State::Ready;
            ++state_.publications;
            traceSlot("copy_ready",index);
        } else {
            status.state = State::DiscardReady;
            traceSlot("copy_ready_stale",index);
        }
        return true;
    }

    void recordKeyTimeout() {
        std::lock_guard<std::mutex> lock(mutex_);
        ++state_.keyTimeouts;
    }

    bool takeConsumerKey(int index, bool discard = false) {
        const HRESULT acquired = slots_[index].consumerKey->AcquireSync(consumerKey, 0);
        if (acquired == S_OK) return true;
        if (acquired == WAIT_TIMEOUT) {
            std::lock_guard<std::mutex> lock(mutex_);
            auto& status = state_.slots[index];
            status.state = !discard && current(status.generation) ? State::Ready : State::DiscardReady;
            ++state_.keyTimeouts;
            traceSlot("consumer_key_timeout",index,discard);
            return false;
        }
        markFailed();
        recycle(index);
        throwStatus(acquired, "handoff consumer key acquisition");
    }

    void returnToProducer(int index, bool discard) {
        const HRESULT result = slots_[index].consumerKey->ReleaseSync(producerKey);
        if (result != S_OK) markFailed();
        recycle(index, discard);
        if (result != S_OK) throwStatus(result, "handoff consumer key release");
    }

    void recycle(int index, bool discard = false) {
        {
            std::lock_guard<std::mutex> lock(mutex_);
            state_.slots[index].state = State::Recycling;
        }
        av_frame_unref(slots_[index].source.get());
        std::lock_guard<std::mutex> lock(mutex_);
        auto& status = state_.slots[index];
        if (status.retained) --state_.retained;
        status.retained = false;
        status.reusable = Clock::now();
        status.state = State::Free;
        if (discard) ++state_.discarded;
        traceSlot("recycle",index,discard);
    }

    void recoverQuery(int index, ID3D11Device* device, HRESULT query, const char* label) {
        if (FAILED(device->GetDeviceRemovedReason())) {
            markFailed();
            recycle(index, true);
            return;
        }
        // The frame and shared allocation must remain pinned if completion
        // could not be established and the device is still live.
        markFailed();
        throwStatus(query, label);
    }

    void markFailed() {
        std::lock_guard<std::mutex> lock(mutex_);
        state_.failed = true;
        discardStaleReady();
    }

    [[noreturn]] static void throwStatus(HRESULT result, const char* label) {
        check(result, label);
        throw std::runtime_error(std::string(label) + " status=" + std::to_string(result));
    }
};
