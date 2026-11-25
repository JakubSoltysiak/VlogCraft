#pragma once
#include "picture_handoff.h"
#include "timeline.h"

// The source selector owns PTS interval decisions. Copies may be prepared
// before that decision; only its exact retained frame can acquire a lease.
class PlaybackPictureLane {
    PictureHandoff ring_;
    std::mutex guard_;
    std::condition_variable changed_;
    std::array<std::weak_ptr<AVFrame>,PictureHandoff::slotCount> desired_;
    uint64_t generation_ = 0;
    int64_t transport_ = -1;
    bool stopping_ = false;
    std::exception_ptr failure_;
    PictureHandoff::Picture lease_;
    std::thread worker_;

    bool requests(const Frame& picture) const {
        return std::any_of(desired_.begin(),desired_.end(),
                           [&](const auto& frame){return frame.lock() == picture;});
    }

    Frame missing(const PictureHandoff::Snapshot& state) const {
        using State = PictureHandoff::State;
        if (std::none_of(state.slots.begin(),state.slots.end(),
                         [](const auto& slot){return slot.state == State::Free;})) return {};
        for (const auto& weak : desired_) {
            auto frame = weak.lock();
            if (!frame) continue;
            const bool prepared = std::any_of(state.slots.begin(),state.slots.end(),[&](const auto& slot){
                return slot.state != State::Free && slot.state != State::DiscardReady &&
                       slot.state != State::Recycling && slot.generation == generation_ &&
                       slot.sourceIdentity.lock() == frame;
            });
            if (!prepared) return frame;
        }
        return {};
    }
    void transfer() {
        using State = PictureHandoff::State;
        try {
            std::unique_lock<std::mutex> lock(guard_);
            while (!stopping_) {
                auto state = ring_.snapshot();
                if (auto frame = missing(state)) {
                    const auto generation = generation_;
                    lock.unlock();
                    const auto slot = ring_.trySubmit(frame.get(),generation,frame,[&]{
                        // The decoder lock can delay enqueue until the clock has
                        // moved on. Recheck the exact request after acquiring it.
                        std::lock_guard<std::mutex> guard(guard_);
                        return !stopping_ && generation == generation_ && requests(frame);
                    });
                    lock.lock();
                    if (slot < 0 && !stopping_ && generation == generation_ && requests(frame))
                        changed_.wait_for(lock,std::chrono::milliseconds(1));
                    // Both slots can be submitted before the first completes.
                    continue;
                }
                const bool queryPending = std::any_of(state.slots.begin(),state.slots.end(),[](const auto& slot){
                    return slot.state == State::CopyPending && !slot.fencePoint;
                });
                if (queryPending) {
                    lock.unlock();
                    const int published = ring_.pollProducerQueries();
                    lock.lock();
                    if (published || stopping_) continue;
                    changed_.wait_for(lock,std::chrono::milliseconds(1));
                } else {
                    changed_.wait(lock);
                }
            }
        } catch (...) {
            std::lock_guard<std::mutex> lock(guard_);
            failure_ = std::current_exception();
        }
    }

public:
    const void* const pool;
    const std::string asset;
    PlaybackPictureLane(const Frame& prototype, const std::string& source, ID3D11Device* consumer)
        : ring_(static_cast<AVD3D11VADeviceContext*>(reinterpret_cast<AVHWFramesContext*>(
              prototype->hw_frames_ctx->data)->device_ctx->hwctx),consumer,prototype.get(),0,true),
          pool(prototype->hw_frames_ctx->data), asset(source) {
        worker_ = std::thread([this]{transfer();});
    }
    ~PlaybackPictureLane() {
        {
            std::lock_guard<std::mutex> lock(guard_);
            stopping_ = true;
            ring_.cancel();
        }
        changed_.notify_one();
        worker_.join();
    }
    bool usingFence() const { return ring_.usingFence(); }
    PictureHandoff::Snapshot snapshot() const { return ring_.snapshot(); }
    void retire() {
        ring_.pollFencedProducer();
        if (ring_.pollConsumer()) {
            std::lock_guard<std::mutex> lock(guard_);
            changed_.notify_one();
        }
    }
    PictureHandoff::Picture select(const Frame& selected, const Frame& floor, const Frame& next, int64_t transport) {
        retire();
        std::lock_guard<std::mutex> lock(guard_);
        if (failure_) std::rethrow_exception(failure_);
        bool reset = transport != transport_;
        if (reset) {
            transport_ = transport;
            ring_.setGeneration(++generation_);
        }
        const auto state = ring_.snapshot();
        if (lease_ && (reset || state.slots[lease_.slot].sourceIdentity.lock() != selected)) {
            ring_.finish(lease_);
            lease_ = {};
        }
        auto first = selected ? selected : floor;
        bool updated = desired_[0].lock() != first || desired_[1].lock() != next;
        desired_ = {first,next};
        bool discard = false;
        for (int i = 0; i < PictureHandoff::slotCount; ++i) {
            const auto& slot = state.slots[i];
            if (slot.state == PictureHandoff::State::CopyPending &&
                Clock::now()-slot.submitted >= std::chrono::seconds(5))
                throw std::runtime_error("handoff copy timed out");
            if (slot.state != PictureHandoff::State::Ready) continue;
            auto frame = slot.sourceIdentity.lock();
            if (frame && (frame == first || frame == next)) {
                if (!lease_ && frame == selected) lease_ = ring_.tryAcquire(generation_,i);
            } else {
                ring_.discardReady(generation_,i);
                discard = true;
            }
        }
        const int recycled = discard ? ring_.pollConsumer() : 0;
        if (reset || updated || recycled) changed_.notify_one();
        return lease_;
    }
};

struct PlaybackHandoff {
    std::array<std::unique_ptr<PlaybackPictureLane>,3> lanes;
    std::array<PictureHandoff::Picture,3> pictures{};
    void trim(const std::map<std::string,bool>& wanted) {
        for (auto& lane : lanes) if (lane && !wanted.count(lane->asset)) lane.reset();
    }
    bool service(size_t i, const Clip& clip, const Frame& selected, Producer& producer,
                 int64_t frame, int64_t generation, ID3D11Device* device) {
        auto [floor,next] = producer.preparationWindow(clip,selected,frame,generation);
        const Frame& prototype = selected ? selected : floor;
        auto& lane = lanes.at(i);
        if (lane && lane->asset != clip.asset) lane.reset();
        if (prototype) {
            if (prototype->format != AV_PIX_FMT_D3D11 || !prototype->hw_frames_ctx)
                throw std::runtime_error("independent handoff requires hardware decode");
            if (!lane || lane->pool != prototype->hw_frames_ctx->data) {
                lane.reset();
                lane = std::make_unique<PlaybackPictureLane>(prototype,clip.asset,device);
            }
            if (next && (!next->hw_frames_ctx || next->hw_frames_ctx->data != lane->pool)) next.reset();
        }
        pictures[i] = lane ? lane->select(selected,floor,next,generation) : PictureHandoff::Picture{};
        return bool(pictures[i]);
    }
};
