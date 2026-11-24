#pragma once
#include "picture_handoff.h"
#include "timeline.h"

// The source selector owns PTS interval decisions. Copies may be prepared
// before that decision; only its exact retained frame can acquire a lease.
class PlaybackPictureLane {
    PictureHandoff ring_;
    std::mutex guard_;
    std::condition_variable changed_;
    std::array<std::weak_ptr<AVFrame>,2> desired_, contents_;
    uint64_t generation_ = 0;
    int64_t transport_ = -1;
    bool stopping_ = false;
    std::exception_ptr failure_;
    PictureHandoff::Picture lease_;
    std::thread worker_;

    Frame missing() const {
        auto state = ring_.snapshot();
        if (state.slots[0].state != PictureHandoff::State::Free &&
            state.slots[1].state != PictureHandoff::State::Free) return {};
        for (const auto& weak : desired_) {
            auto frame = weak.lock();
            if (!frame) continue;
            bool prepared = false;
            for (int i = 0; i < 2; ++i) {
                const auto& slot = state.slots[i];
                prepared |= slot.state != PictureHandoff::State::Free &&
                    slot.generation == generation_ && contents_[i].lock() == frame;
            }
            if (!prepared) return frame;
        }
        return {};
    }
    void transfer() {
        try {
            std::unique_lock<std::mutex> lock(guard_);
            for (;;) {
                Frame frame;
                changed_.wait(lock,[&]{return stopping_ || bool(frame = missing());});
                if (stopping_) return;
                const auto generation = generation_;
                lock.unlock();
                int slot = ring_.trySubmit(frame.get(),generation);
                lock.lock();
                if (slot < 0) {
                    changed_.wait_for(lock,std::chrono::milliseconds(1));
                    continue;
                }
                contents_[slot] = frame;
                lock.unlock();
                const auto deadline = Clock::now() + std::chrono::seconds(5);
                while (ring_.slotState(slot) == PictureHandoff::State::CopyPending) {
                    if (Clock::now() >= deadline) throw std::runtime_error("handoff copy timed out");
                    ring_.pollProducer();
                    if (ring_.slotState(slot) == PictureHandoff::State::CopyPending) SwitchToThread();
                }
                lock.lock();
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
    void retire() {
        if (ring_.pollConsumer()) {
            std::lock_guard<std::mutex> lock(guard_);
            changed_.notify_one();
        }
    }
    PictureHandoff::Picture select(const Frame& selected, const Frame& floor, const Frame& next, int64_t transport) {
        const int recycled = ring_.pollConsumer();
        std::lock_guard<std::mutex> lock(guard_);
        if (failure_) std::rethrow_exception(failure_);
        bool reset = transport != transport_;
        if (reset) {
            transport_ = transport;
            ring_.setGeneration(++generation_);
        }
        if (lease_ && (reset || contents_[lease_.slot].lock() != selected)) {
            ring_.finish(lease_);
            lease_ = {};
        }
        auto first = selected ? selected : floor;
        bool updated = desired_[0].lock() != first || desired_[1].lock() != next;
        desired_ = {first,next};
        for (int i = 0; i < 2; ++i) {
            if (ring_.slotState(i) != PictureHandoff::State::Ready) continue;
            auto frame = contents_[i].lock();
            if (frame && (frame == first || frame == next)) {
                if (!lease_ && frame == selected) lease_ = ring_.tryAcquire(generation_,i);
            } else {
                auto obsolete = ring_.tryAcquire(generation_,i);
                if (obsolete) ring_.finish(obsolete);
            }
        }
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
    bool service(size_t i, const Clip& clip, Frame selected, Producer& producer,
                 int64_t generation, ID3D11Device* device) {
        auto [floor,next] = producer.preparationWindow(clip,selected,generation);
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
