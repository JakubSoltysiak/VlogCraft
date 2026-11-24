#pragma once
#include "picture_handoff.h"
#include "timeline.h"

// Each active layer has a bounded copy endpoint. The render loop never takes
// the decoder's FFmpeg mutex, including when a source advances during a copy.
class PlaybackPictureLane {
    PictureHandoff ring_;
    std::mutex guard_;
    std::condition_variable changed_;
    Frame request_;
    uint64_t serial_ = 0;
    int64_t epoch_ = -1;
    bool stopping_ = false;
    std::exception_ptr failure_;
    PictureHandoff::Picture lease_;
    std::thread worker_;

    void transfer() {
        try {
            uint64_t copied = 0;
            std::unique_lock<std::mutex> lock(guard_);
            while (!stopping_) {
                changed_.wait(lock,[&]{return stopping_ || copied != serial_;});
                if (stopping_) break;
                auto frame = request_;
                auto serial = serial_;
                lock.unlock();
                const int slot = ring_.trySubmit(frame.get(),serial);
                if (slot >= 0) {
                    // Finish each accepted GPU copy, including superseded copies.
                    // The ring tests its generation again before publication.
                    const auto deadline = Clock::now() + std::chrono::seconds(5);
                    while (ring_.slotState(slot) == PictureHandoff::State::CopyPending) {
                        if (Clock::now() >= deadline) throw std::runtime_error("handoff copy timed out");
                        ring_.pollProducer();
                        if (ring_.slotState(slot) == PictureHandoff::State::CopyPending) SwitchToThread();
                    }
                    copied = serial;
                }
                lock.lock();
                if (slot < 0 && !stopping_ && serial == serial_)
                    changed_.wait_for(lock,std::chrono::milliseconds(1));
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
              prototype->hw_frames_ctx->data)->device_ctx->hwctx),consumer,prototype.get(),0),
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
        // The ring seals any outstanding drawing lease and drains both devices
        // before releasing its retained frames. The consumer thread owns teardown.
    }
    PictureHandoff::Picture select(const Frame& frame, int64_t generation) {
        ring_.pollConsumer();
        std::lock_guard<std::mutex> lock(guard_);
        if (failure_) std::rethrow_exception(failure_);
        if (frame != request_ || generation != epoch_) {
            if (lease_) ring_.finish(lease_);
            lease_ = {};
            request_ = frame;
            epoch_ = generation;
            ring_.setGeneration(++serial_);
            changed_.notify_one();
        }
        if (!lease_) lease_ = ring_.tryAcquire(serial_);
        return lease_;
    }
};

struct PlaybackHandoff {
    std::array<std::unique_ptr<PlaybackPictureLane>,3> lanes;
    std::array<PictureHandoff::Picture,3> pictures{};
    void trim(const std::map<std::string,bool>& wanted) {
        for (auto& lane : lanes) if (lane && !wanted.count(lane->asset)) lane.reset();
    }
    bool prepare(const std::vector<std::pair<const Clip*,Frame>>& selected, int64_t generation,
                 ID3D11Device* device) {
        bool ready = true;
        for (size_t i = 0; i < lanes.size(); ++i) {
            if (i >= selected.size()) { lanes[i].reset(); pictures[i] = {}; continue; }
            const auto& frame = selected[i].second;
            if (frame->format != AV_PIX_FMT_D3D11 || !frame->hw_frames_ctx)
                throw std::runtime_error("independent handoff requires hardware decode");
            auto& lane = lanes[i];
            if (!lane || lane->pool != frame->hw_frames_ctx->data || lane->asset != selected[i].first->asset) {
                lane.reset();
                lane = std::make_unique<PlaybackPictureLane>(frame,selected[i].first->asset,device);
            }
            pictures[i] = lane->select(frame,generation);
            ready &= bool(pictures[i]);
        }
        return ready;
    }
};
