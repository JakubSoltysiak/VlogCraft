#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <algorithm>
#include <chrono>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <future>
#include <iostream>
#include <mutex>
#include <string>
#include <vector>

using Clock = std::chrono::steady_clock;
#include "../native/stall_watch.h"

using namespace std::chrono_literals;
constexpr int64_t generation = 7;
constexpr int64_t endFrame = 120;

// The fixture has no GUI observer, media files or GPU. The simulated renderer
// keeps publishing heartbeats while a producer is blocked on a real mutex.
void rendererTick(StallWatch& watch, int64_t frame, int64_t gen) {
    watch.loop.set({frame, gen, frame * 1000000 / 60, (frame + 1) * 1000000 / 60, watch.now()});
}

void returnedDraw(StallWatch& watch, int64_t frame, uint64_t count) {
    rendererTick(watch, frame, generation);
    watchGPU(count, count, frame, generation);
    watchPresent();
    watch.submit.set({frame, generation, watch.now()});
}

bool blocked(StallWatch& watch) {
    WatchThread renderer(0);
    watch.start(endFrame + 1, 60, 1);
    watchClock(0, generation, true);
    uint64_t submitted = 0;
    for (int frame = 0; frame <= 12; frame += 2) {
        returnedDraw(watch, frame, ++submitted);
        std::this_thread::sleep_for(16ms);
    }

    WatchLease producer;
    if (producer.lane != 1) return false;
    watchSource(producer.lane, 3, 12, 1, 90000);
    watchQueue(producer.lane, 18000, 16500, INT64_MIN, 0, 2, 0, 3, false, false, false);
    std::mutex device;
    std::unique_lock held(device);
    std::promise<void> entered;
    auto ready = entered.get_future();
    std::thread decode([&] {
        WatchThread source(producer.lane);
        WatchStage receive("receive_picture");
        watchPacket(18000, 15000);
        watchDevice(true, false);
        entered.set_value();
        std::lock_guard acquired(device);
        watchDevice(false, true);
        watchQueue(producer.lane, 18000, 18000, 19500, 1, 2, 0, 3, true, false, false);
        watchDevice(false, false);
    });
    ready.wait();
    constexpr int64_t beforeBlock = 12;
    watchClock(beforeBlock * 1000000 / 60, generation, true);
    const auto began = watch.now();
    auto live = std::filesystem::u8path(watch.path + ".live");
    auto timeout = Clock::now() + 8s;
    std::error_code fileError;
    while (!std::filesystem::exists(live, fileError) && Clock::now() < timeout) {
        rendererTick(watch, beforeBlock + (watch.now() - began) * 60 / 1000000, generation);
        std::this_thread::sleep_for(8ms);
    }
    const bool capturedWhileBlocked = std::filesystem::exists(live, fileError);
    held.unlock();
    decode.join();

    // The live artifact is the handshake to release the blocked producer.
    // Publish the exact end frame and allow the watchdog to retain recovery.
    if (capturedWhileBlocked) {
        returnedDraw(watch, endFrame, ++submitted);
        std::this_thread::sleep_for(420ms);
    } else {
        std::cerr << "The watchdog did not write a live artifact while the decoder was blocked.\n";
    }
    return capturedWhileBlocked;
}

void excluded(StallWatch& watch, bool seeking) {
    WatchThread renderer(0);
    // Deliberately old progress at a position with frames still remaining.
    // During a seek the render loop still shows the old generation.
    watch.submit.set({12, generation, watch.now() - 250000});
    rendererTick(watch, 12, generation);
    watchClock(2000000, seeking ? generation + 1 : generation, seeking);
    watch.start(endFrame + 1, 60, 1);
    std::this_thread::sleep_for(350ms);
}

void retention(StallWatch& watch) {
    for (int64_t age : {150000, 400000, 200000, 900000, 250000}) {
        StallWatch::Incident incident;
        incident.age = age;
        watch.keep(std::move(incident));
    }
    watch.write();
}

void requests(StallWatch& watch) {
    WatchRequest row;
    row.fields = {0, 0, 18, generation, 0, 300000, 300000, 7, 1, 17, generation, 0};
    watch.publishRequest(row);  // Paused and unavailable.
    row.fields[2] = 19;
    row.fields[4] = 1;
    row.fields[5] = 316665;
    row.fields[6] = 316667;
    watch.publishRequest(row);  // Deadline is still in the future.
    row.fields[2] = 20;
    row.fields[5] = 333333;
    row.fields[6] = 333334;
    row.at(1)[12] = static_cast<int64_t>(PictureReason::missingSuccessor);
    watch.publishRequest(row);
    watch.publishRequest(row);  // Redundant retry.
    row.fields[8] = 15;
    row.at(1)[12] = static_cast<int64_t>(PictureReason::live);
    watch.publishRequest(row);
    watch.readRequestsInto(nullptr);
    watch.write();
}

int wmain(int argc, wchar_t** argv) {
    if (argc != 3) return 2;
    StallWatch watch(std::filesystem::path(argv[2]).u8string());
    const std::wstring mode = argv[1];
    if (mode == L"blocked") return blocked(watch) ? 0 : 3;
    if (mode == L"pause" || mode == L"seek") {
        excluded(watch, mode == L"seek");
        return 0;
    }
    if (mode == L"retention") {
        retention(watch);
        return 0;
    }
    if (mode == L"requests") {
        requests(watch);
        return 0;
    }
    return 2;
}
