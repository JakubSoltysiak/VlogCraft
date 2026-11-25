#pragma once

#include "media.h"
#include <mutex>

// Opt-in capture of a short playback run. Ring IDs, slot serials and
// process-local picture keys identify work without retaining any frames.
class PictureHandoffTrace {
    static constexpr size_t limit = 65536;
    struct Event {
        const char* name;
        int64_t us, generation, sequence, pts, value;
        uint64_t serial;
        uintptr_t identity, texture;
        intptr_t slice;
        int ring, lane, slot;
    };
    const Clock::time_point start_ = Clock::now();
    std::mutex mutex_;
    std::vector<Event> events_;
    std::ofstream output_;
    size_t dropped_ = 0;
    int rings_ = 0;

    uintptr_t key(const void* value) const {
        return value ? reinterpret_cast<uintptr_t>(value) ^ reinterpret_cast<uintptr_t>(this) : 0;
    }

public:
    explicit PictureHandoffTrace(const char* path) {
        const auto file = std::filesystem::u8path(path);
        if (std::filesystem::exists(file)) throw std::runtime_error("Handoff trace already exists");
        output_.open(file);
        if (!output_) throw std::runtime_error("Cannot open handoff trace");
        events_.reserve(limit);
    }
    ~PictureHandoffTrace() {
        output_ << "# capacity=" << limit << ",stored=" << events_.size() << ",dropped=" << dropped_
                << "\nindex,us,event,ring,lane,generation,sequence,slot,serial,picture,texture,slice,pts,value\n";
        for (size_t i = 0; i < events_.size(); ++i) {
            const auto& e = events_[i];
            output_ << i << ',' << e.us << ',' << e.name << ',' << e.ring << ',' << e.lane
                    << ',' << e.generation << ',' << e.sequence << ',' << e.slot << ',' << e.serial
                    << ',' << e.identity << ',' << e.texture << ',' << e.slice << ',' << e.pts << ',' << e.value << '\n';
        }
    }
    // Only the compositor constructs rings.
    int openRing() { return ++rings_; }

    void add(const char* event, int ring, int lane, int64_t generation, int64_t sequence,
             int slot = -1, uint64_t serial = 0, const AVFrame* frame = nullptr, int64_t value = 0) {
        std::lock_guard<std::mutex> lock(mutex_);
        if (events_.size() == limit) {
            ++dropped_;
            return;
        }
        const auto us = std::chrono::duration_cast<std::chrono::microseconds>(Clock::now()-start_).count();
        const auto texture = frame && frame->format == AV_PIX_FMT_D3D11 ? key(frame->data[0]) : 0;
        events_.push_back({event,us,generation,sequence,frame ? frame->best_effort_timestamp : AV_NOPTS_VALUE,
                           value,serial,key(frame),texture,texture ? reinterpret_cast<intptr_t>(frame->data[1]) : -1,
                           ring,lane,slot});
    }
};
