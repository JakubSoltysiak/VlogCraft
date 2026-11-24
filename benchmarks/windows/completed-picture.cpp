// Qualification of a completed decoder picture on an independent compositor device.
#include "../../native/media.h"
#include "../../native/picture_handoff.h"
#include "handoff-pixels.h"
#include <d3d11_4.h>
#include <dxgi1_4.h>
#include <thread>
#include <future>
#include <condition_variable>
#include <wrl/client.h>

namespace {
using Microsoft::WRL::ComPtr;
constexpr int pictureCount = 8;
constexpr auto timeout = std::chrono::seconds(5);
struct HW {
    AVBufferRef* ref = nullptr;
    ~HW() { av_buffer_unref(&ref); }
};
using FramePtr = std::shared_ptr<AVFrame>;
FramePtr cpuFrame() {
    FramePtr frame(av_frame_alloc(), [](AVFrame* p){ av_frame_free(&p); });
    if (!frame) throw std::bad_alloc();
    return frame;
}
void require(bool yes, const char* message) {
    if (!yes) throw std::runtime_error(message);
}
template<class Pred> void until(Pred condition, const char* failure) {
    const auto limit = Clock::now() + timeout;
    while (!condition()) {
        require(Clock::now() < limit, failure);
        std::this_thread::yield();
    }
}
int64_t tick() { LARGE_INTEGER q; QueryPerformanceCounter(&q); return q.QuadPart; }
int64_t frequency() { LARGE_INTEGER q; QueryPerformanceFrequency(&q); return q.QuadPart; }
double ms(int64_t ticks) { return 1000. * ticks / frequency(); }

// Wrap the documented, recursive FFmpeg callbacks only in this test process.
// The controlled barrier is reached *after* the genuine decoder mutex is held.
struct DecodeBoundary {
    AVD3D11VADeviceContext* hw;
    void* opaque;
    void (*lock)(void*);
    void (*unlock)(void*);
    std::mutex guard;
    std::condition_variable changed;
    bool armed = false, controlled = false, resume = false, expired = false;
    int64_t entered = 0, released = 0, publicationEntered = 0;
    static thread_local int depth;
    static thread_local bool trackPublication;
    explicit DecodeBoundary(AVD3D11VADeviceContext* d)
        : hw(d), opaque(d->lock_ctx), lock(d->lock), unlock(d->unlock) {
        d->lock_ctx = this;
        d->lock = [](void* p) {
            auto& self = *static_cast<DecodeBoundary*>(p);
            if (trackPublication) {
                std::lock_guard<std::mutex> lock(self.guard);
                self.publicationEntered = tick();
                self.changed.notify_all();
            }
            self.lock(self.opaque);
            if (++depth == 1) {
                std::unique_lock<std::mutex> g(self.guard);
                if (self.armed && !self.entered) {
                    self.entered = tick();
                    self.changed.notify_all();
                    if (self.controlled && !self.changed.wait_for(g, timeout, [&]{ return self.resume; }))
                        self.expired = true;
                }
            }
        };
        d->unlock = [](void* p) {
            auto& self = *static_cast<DecodeBoundary*>(p);
            if (--depth == 0) {
                std::lock_guard<std::mutex> g(self.guard);
                if (self.armed && self.entered && !self.released) self.released = tick();
            }
            self.unlock(self.opaque);
        };
    }
    ~DecodeBoundary() { hw->lock = lock; hw->unlock = unlock; hw->lock_ctx = opaque; }
    void arm(bool block) {
        std::lock_guard<std::mutex> g(guard);
        armed = true; controlled = block; resume = expired = false;
        entered = released = publicationEntered = 0;
    }
    void waitEntered() {
        std::unique_lock<std::mutex> g(guard);
        require(changed.wait_for(g, timeout, [&]{ return entered != 0; }), "next picture did not enter FFmpeg device transaction");
    }
    void waitPublicationEntered() {
        std::unique_lock<std::mutex> g(guard);
        require(changed.wait_for(g, timeout, [&]{ return publicationEntered != 0; }),
                "legacy publication did not attempt to enter the device lock");
    }
    void release() {
        std::lock_guard<std::mutex> g(guard); resume = true; changed.notify_all();
    }
};
thread_local int DecodeBoundary::depth = 0;
thread_local bool DecodeBoundary::trackPublication = false;

struct DeviceLock {
    AVD3D11VADeviceContext* const hw;
    explicit DeviceLock(AVD3D11VADeviceContext* device) : hw(device) { hw->lock(hw->lock_ctx); }
    ~DeviceLock() { hw->unlock(hw->lock_ctx); }
    DeviceLock(const DeviceLock&) = delete;
    DeviceLock& operator=(const DeviceLock&) = delete;
};

void probePublication(AVD3D11VADeviceContext* hw, Decoder& decoded, PictureHandoff& ring,
                      DecodeBoundary& boundary, DXGI_FORMAT format) {
    using State = PictureHandoff::State;
    constexpr uint64_t generation = 1;
    constexpr UINT64 fenceValue = 1;
    ComPtr<ID3D11Device5> device;
    ComPtr<ID3D11DeviceContext4> context;
    ComPtr<ID3D11Fence> fence;
    const char* fenceStage = "device5";
    HRESULT fenceResult = hw->device->QueryInterface(IID_PPV_ARGS(&device));
    if (SUCCEEDED(fenceResult)) {
        fenceStage = "context4";
        fenceResult = hw->device_context->QueryInterface(IID_PPV_ARGS(&context));
    }
    if (SUCCEEDED(fenceResult)) {
        fenceStage = "create_fence";
        fenceResult = device->CreateFence(0, D3D11_FENCE_FLAG_NONE, IID_PPV_ARGS(&fence));
    }

    const auto pts = decoded.frame->best_effort_timestamp;
    int slot;
    {
        // This outer scope holds FFmpeg's recursive lock continuously from
        // copy submission through the signal, with no other producer commands.
        DeviceLock submitLock(hw);
        slot = ring.trySubmit(decoded.frame, generation);
        require(slot >= 0 && ring.slotState(slot) == State::CopyPending, "ring did not submit its copy");
        if (SUCCEEDED(fenceResult)) {
            fenceStage = "signal";
            fenceResult = context->Signal(fence.Get(), fenceValue);
            if (SUCCEEDED(fenceResult)) context->Flush();
        }
    }

    auto consumeAndDrain = [&] {
        auto picture = ring.tryAcquire(generation, slot);
        require(picture && picture.pts == pts, "published picture did not match the submitted source PTS");
        ring.finish(picture);
        require(ring.drain(std::chrono::seconds(3)) && !ring.snapshot().retained, "publication probe did not drain");
    };
    if (FAILED(fenceResult)) {
        check(hw->device->GetDeviceRemovedReason(), "producer device health");
        until([&] { ring.pollProducer(); return ring.slotState(slot) == State::Ready; },
              "legacy publication fallback did not complete");
        consumeAndDrain();
        std::printf("{\"type\":\"publication\",\"format\":%u,\"fence_supported\":false,"
                    "\"failed_stage\":\"%s\",\"hresult\":\"0x%08lx\",\"legacy_fallback_drained\":true}\n",
                    static_cast<unsigned>(format), fenceStage, static_cast<unsigned long>(fenceResult));
        return;
    }

    const auto completedBeforeDecode = fence->GetCompletedValue();
    boundary.arm(true);
    auto next = std::async(std::launch::async, [&] { require(decoded.next(), "missing subsequent decoded picture"); });
    std::future<std::pair<int, int64_t>> publication;
    int64_t observed = 0;
    try {
        boundary.waitEntered();
        publication = std::async(std::launch::async, [&] {
            DecodeBoundary::trackPublication = true;
            const int count = ring.pollProducer();
            return std::make_pair(count, tick());
        });
        boundary.waitPublicationEntered();
        until([&] {
            const auto completed = fence->GetCompletedValue();
            require(completed != UINT64_MAX, "producer fence reported device removal");
            return completed >= fenceValue;
        }, "copy fence did not complete during the controlled decoder lock");
        observed = tick();
        require(publication.wait_for(std::chrono::milliseconds(0)) == std::future_status::timeout &&
                ring.slotState(slot) == State::CopyPending && ring.snapshot().retained == 1,
                "legacy query published or dropped ownership while FFmpeg held the device lock");
        require(!ring.tryAcquire(generation, slot), "producer fence alone exposed the consumer picture");
        boundary.release();
    } catch (...) {
        boundary.release();
        throw;
    }
    const auto [count, published] = publication.get();
    next.get();
    require(!boundary.expired && boundary.entered <= boundary.publicationEntered &&
            boundary.publicationEntered <= observed && observed < boundary.released &&
            boundary.released <= published && count == 1 && ring.slotState(slot) == State::Ready,
            "publication and decoder lock did not overlap as required");
    consumeAndDrain();
    std::printf("{\"type\":\"publication\",\"format\":%u,\"fence_supported\":true,"
                "\"fence_complete_on_predecode_sample\":%s,\"legacy_poll_blocked\":true,"
                "\"fence_observed_inside_decoder_lock\":true,\"published_after_decoder_unlock\":true,"
                "\"fence_observation_to_unlock_ms\":%.6f,\"fence_observation_to_publication_ms\":%.6f,"
                "\"legacy_drained\":true}\n",
                static_cast<unsigned>(format), completedBeforeDecode >= fenceValue ? "true" : "false",
                ms(boundary.released - observed), ms(published - observed));
}

int64_t usage(IDXGIAdapter3* a, DXGI_MEMORY_SEGMENT_GROUP segment) {
    DXGI_QUERY_VIDEO_MEMORY_INFO info{};
    check(a->QueryVideoMemoryInfo(0, segment, &info), "process video-memory accounting");
    return static_cast<int64_t>(info.CurrentUsage);
}

enum class Mode { Verify, Memory, Publication };

void run(const char* fixture, Mode mode) {
    HW device;
    avcheck(av_hwdevice_ctx_create(&device.ref, AV_HWDEVICE_TYPE_D3D11VA, nullptr, nullptr, 0), "FFmpeg device");
    auto* hw = reinterpret_cast<AVD3D11VADeviceContext*>(reinterpret_cast<AVHWDeviceContext*>(device.ref->data)->hwctx);
    hw->BindFlags |= D3D11_BIND_SHADER_RESOURCE;
    std::vector<FramePtr> reference;
    if (mode == Mode::Verify) {
        Decoder baseline(fixture, device.ref, true, 15);
        for (int i = 0; i < pictureCount; ++i) {
            require(baseline.next(), "short reference");
            auto out = cpuFrame();
            avcheck(av_hwframe_transfer_data(out.get(), baseline.frame, 0), "reference download");
            out->width = baseline.frame->width; out->height = baseline.frame->height;
            out->best_effort_timestamp = baseline.frame->best_effort_timestamp;
            reference.push_back(std::move(out));
        }
    }
    ComPtr<IDXGIDevice> dxgi;
    check(hw->device->QueryInterface(IID_PPV_ARGS(&dxgi)), "producer DXGI");
    ComPtr<IDXGIAdapter> adapter;
    check(dxgi->GetAdapter(&adapter), "producer adapter");
    ComPtr<IDXGIAdapter3> memory;
    check(adapter.As(&memory), "segment budgets");
    ComPtr<ID3D11Device> consumer;
    ComPtr<ID3D11DeviceContext> context;
    check(D3D11CreateDevice(adapter.Get(), D3D_DRIVER_TYPE_UNKNOWN, nullptr, 0, nullptr, 0,
          D3D11_SDK_VERSION, &consumer, nullptr, &context), "same-adapter consumer");
    DecodeBoundary boundary(hw);
    Decoder decoded(fixture, device.ref, true, 15);
    require(decoded.next() && decoded.frame->format == AV_PIX_FMT_D3D11, "hardware decode");
    D3D11_TEXTURE2D_DESC desc{};
    reinterpret_cast<ID3D11Texture2D*>(decoded.frame->data[0])->GetDesc(&desc);
    const auto localBefore = usage(memory.Get(), DXGI_MEMORY_SEGMENT_GROUP_LOCAL);
    const auto nonlocalBefore = usage(memory.Get(), DXGI_MEMORY_SEGMENT_GROUP_NON_LOCAL);
    PictureHandoff ring(hw, consumer.Get(), decoded.frame, 1);
    const auto localDelta = usage(memory.Get(), DXGI_MEMORY_SEGMENT_GROUP_LOCAL) - localBefore;
    const auto nonlocalDelta = usage(memory.Get(), DXGI_MEMORY_SEGMENT_GROUP_NON_LOCAL) - nonlocalBefore;
    std::printf("{\"type\":\"resources\",\"format\":%u,\"width\":%u,\"height\":%u,\"pool\":%u,"
                "\"local_delta\":%lld,\"nonlocal_delta\":%lld}\n", desc.Format, desc.Width, desc.Height,
                desc.ArraySize, (long long)localDelta, (long long)nonlocalDelta);
    if (mode == Mode::Publication) {
        probePublication(hw, decoded, ring, boundary, desc.Format);
        return;
    }
    if (mode == Mode::Memory) {
        // Isolate both handoff images from CPU reference/staging and shader verification.
        // Fill with the same already materialized decoder slice, holding both slots.
        int64_t localPeak = localBefore, nonlocalPeak = nonlocalBefore;
        for (int i = 0; i < 2; ++i) {
            int slot = ring.trySubmit(decoded.frame,1);
            require(slot >= 0,"memory probe missing slot");
            until([&]{ring.pollProducer(); return ring.slotState(slot)==PictureHandoff::State::Ready;},
                  "memory probe copy deadline");
            localPeak = (std::max)(localPeak,usage(memory.Get(),DXGI_MEMORY_SEGMENT_GROUP_LOCAL));
            nonlocalPeak = (std::max)(nonlocalPeak,usage(memory.Get(),DXGI_MEMORY_SEGMENT_GROUP_NON_LOCAL));
        }
        require(ring.snapshot().peakSlots == 2, "memory probe did not touch both slots");
        std::printf("{\"type\":\"memory\",\"visible_bytes_per_image\":%llu,\"storage_bytes_per_image\":%llu,"
                    "\"local_before\":%lld,\"nonlocal_before\":%lld,\"local_peak\":%lld,\"nonlocal_peak\":%lld}\n",
                    (unsigned long long)ring.visiblePayloadBytes(),(unsigned long long)ring.storagePayloadBytes(),
                    (long long)localBefore,(long long)nonlocalBefore,(long long)localPeak,(long long)nonlocalPeak);
        require(ring.drain(std::chrono::seconds(3)), "memory probe teardown deadline");
        return;
    }
    HandoffPixels pixels(consumer.Get(), decoded.frame->width, decoded.frame->height, desc.Format);
    ComPtr<ID3D11Query> verified;
    D3D11_QUERY_DESC query{D3D11_QUERY_EVENT,0};
    check(consumer->CreateQuery(&query,&verified), "verification completion query");
    using State = PictureHandoff::State;
    uint64_t generation = 1;
    std::array<unsigned,2> uses{};
    auto submit = [&]() {
        const int slot = ring.trySubmit(decoded.frame, generation);
        require(slot >= 0 && slot < 2, "expected free slot");
        ++uses[slot];
        return slot;
    };
    auto ready = [&](int slot) {
        until([&]{ ring.pollProducer(); return ring.slotState(slot) == State::Ready; }, "copy completion timeout");
    };
    auto consume = [&](int slot, int n) {
        const auto start = tick();
        auto picture = ring.tryAcquire(generation, slot);
        require(picture.slot == slot, "ready picture not acquired");
        pixels.submit(context.Get(), picture.luma, picture.chroma);
        ring.finish(picture);
        until([&]{ ring.pollConsumer(); return ring.slotState(slot) == State::Free; }, "render completion timeout");
        const auto completed = tick();
        pixels.stage(context.Get());
        context->End(verified.Get());
        context->Flush();
        until([&]{
            const auto result = context->GetData(verified.Get(),nullptr,0,D3D11_ASYNC_GETDATA_DONOTFLUSH);
            check(result,"verification completion");
            return result == S_OK;
        }, "verification copy timeout");
        const auto bytes = pixels.verify(context.Get(), reference[n].get(), picture.pts);
        const auto measured = ring.snapshot().slots[slot];
        std::printf("{\"type\":\"picture\",\"index\":%d,\"slot\":%d,\"pts\":%lld,\"bytes\":%llu,"
                    "\"copy_gpu_ms\":%.8f,\"copy_submit_cpu_ms\":%.8f,\"submit_to_publish_ms\":%.8f,"
                    "\"render_and_retire_ms\":%.8f,\"finish_to_completion_ms\":%.8f,\"completion_to_reuse_ms\":%.8f}\n",
                    n, slot, (long long)picture.pts, (unsigned long long)bytes,
                    measured.gpuCopyValid ? measured.gpuCopyMs : -1., measured.copyCpuMs,
                    std::chrono::duration<double,std::milli>(measured.published-measured.submitted).count(),
                    ms(completed-start),
                    std::chrono::duration<double,std::milli>(measured.consumerCompleted-measured.consumerSubmitted).count(),
                    std::chrono::duration<double,std::milli>(measured.reusable-measured.consumerCompleted).count());
        return std::make_pair(start, completed);
    };
    for (int n = 0; n < pictureCount; n += 2) {
        if (n) require(decoded.next(), "short fixture");
        int64_t begin = tick();
        const int a = submit(); ready(a);
        const auto published = tick();
        const bool block = n == 0;
        boundary.arm(block);
        auto next = std::async(std::launch::async, [&] {
            const auto t = tick(); require(decoded.next(), "missing subsequent picture");
            return std::make_pair(t, tick());
        });
        std::pair<int64_t,int64_t> render;
        try {
            boundary.waitEntered();
            if (n < 4) render = consume(a,n);
            boundary.release();
        } catch (...) { boundary.release(); throw; }
        const auto decode = next.get();
        boundary.armed = false;
        require(!boundary.expired, "decoder control expired");
        if (block) require(render.first >= boundary.entered && render.second < boundary.released, "controlled overlap failed");
        const int b = submit();
        if (n >= 4) {
            require(a != b && ring.trySubmit(decoded.frame,generation) < 0, "backpressure failed");
            require(ring.tryAcquire(generation,b).slot < 0, "unpublished picture exposed");
            render = consume(a,n);
        }
        ready(b); consume(b,n+1);
        std::printf("{\"type\":\"ordering\",\"index\":%d,\"controlled\":%s,\"copy_to_ready_ms\":%.8f,"
                    "\"ffmpeg_device_span_ms\":%.8f,\"render_start_from_lock_ms\":%.8f,"
                    "\"render_complete_from_lock_ms\":%.8f,\"within_next_call\":%s,\"within_device_lock\":%s}\n",
                    n, block?"true":"false", ms(published-begin), ms(boundary.released-boundary.entered),
                    ms(render.first-boundary.entered), ms(render.second-boundary.entered),
                    render.first>=decode.first && render.second<=decode.second?"true":"false",
                    render.first>=boundary.entered && render.second<=boundary.released?"true":"false");
    }
    require(uses[0] >= 2 && uses[1] >= 2 && ring.idle(), "insufficient slot reuse");
    // Both cancellations must be preceded by an actual incomplete GPU-query observation.
    // Repeats are bounded and disclosed; a host-side pending state alone is insufficient.
    bool copySeen = false, renderSeen = false;
    for (int pass = 0; pass < 12 && !copySeen; ++pass) {
        const int id = submit();
        ring.pollProducer();
        const auto status = ring.snapshot().slots[id];
        copySeen = ring.slotState(id) == State::CopyPending && status.copyPendingPolls > 0;
        if (copySeen) require(status.retained,"copy cancellation lost its frame");
        ring.setGeneration(++generation);
        require(ring.tryAcquire(generation-1,id).slot < 0, "stale picture acquired");
        until([&]{ring.pollProducer(); ring.pollConsumer(); return ring.idle();}, "stale copy retirement");
        std::printf("{\"type\":\"cancel_copy\",\"attempt\":%d,\"observed_pending\":%s}\n",pass+1,copySeen?"true":"false");
    }
    require(copySeen, "did not observe pending GPU copy");
    for (int pass = 0; pass < 12 && !renderSeen; ++pass) {
        const int id = submit(); ready(id);
        auto picture = ring.tryAcquire(generation,id);
        require(picture.slot == id, "cancel fixture not ready");
        pixels.submit(context.Get(),picture.luma,picture.chroma); ring.finish(picture);
        ring.pollConsumer();
        renderSeen = ring.slotState(id) == State::ConsumerPending && ring.snapshot().slots[id].consumerPendingPolls > 0;
        if (renderSeen) {
            require(ring.snapshot().slots[id].retained,"consumer cancellation lost its frame");
            ring.cancel();
        }
        until([&]{ring.pollConsumer(); return ring.idle();}, "cancelled render retirement");
        std::printf("{\"type\":\"cancel_render\",\"attempt\":%d,\"observed_pending\":%s}\n",pass+1,renderSeen?"true":"false");
    }
    require(renderSeen && ring.trySubmit(decoded.frame,generation)<0, "cancelled ring accepted work");
    const auto stats = ring.snapshot();
    require(stats.peakSlots == 2 && stats.peakRetained == 2 && !stats.retained, "handoff frame bound");
    std::printf("{\"type\":\"complete\",\"uses0\":%u,\"uses1\":%u,\"peak_slots\":%u,\"peak_retained\":%u,"
                "\"retained_after_cancel\":%u,\"backpressure\":%llu,\"storage_bytes_per_image\":%llu}\n",
                uses[0], uses[1], stats.peakSlots, stats.peakRetained, stats.retained,
                (unsigned long long)stats.backpressure, (unsigned long long)ring.storagePayloadBytes());
}
}
int main(int argc, char** argv) {
    if (argc < 2 || argc > 3) return 2;
    Mode mode = Mode::Verify;
    if (argc == 3) {
        if (!std::strcmp(argv[2], "--memory-only")) mode = Mode::Memory;
        else if (!std::strcmp(argv[2], "--publication")) mode = Mode::Publication;
        else return 2;
    }
    try { run(argv[1], mode); }
    catch (const std::exception& e) { std::fprintf(stderr,"%s\n", e.what()); return 1; }
    return 0;
}
