#pragma once

#include <algorithm>
#include <cmath>
#include <condition_variable>
#include <cstdint>
#include <immintrin.h>
#include <mutex>
#include <thread>
#include <vector>

namespace render_phase2 {

struct Pixel {
    float r, g, b, a;
};

// Every source pixel is float32, premultiplied and display-linear Rec.2020.
// Float constants are shared verbatim with the D3D11 constant buffer.
struct Layer {
    float scale, cosine, sine, x;
    float y, opacity, radius, feather;
    std::uint32_t slice, mask, reserved1, reserved2;
};

struct Frame {
    std::uint32_t width, height, layers;
    float dissolve;
    Layer layer[3];
};

static_assert(sizeof(Pixel) == 16 && sizeof(Layer) == 48 && sizeof(Frame) == 160);

template<bool Simd> struct Math;

template<> struct Math<false> {
    using Value = Pixel;
    static Value load(const Pixel* pixel) { return *pixel; }
    static Value zero() { return {}; }
    static Value add(Value a, Value b) { return {a.r+b.r,a.g+b.g,a.b+b.b,a.a+b.a}; }
    static Value mul(Value a, float b) { return {a.r*b,a.g*b,a.b*b,a.a*b}; }
    static float alpha(Value a) { return a.a; }
    static void store(Pixel* pixel, Value a) { *pixel = a; }
};

template<> struct Math<true> {
    using Value = __m128;
    static Value load(const Pixel* pixel) { return _mm_loadu_ps(&pixel->r); }
    static Value zero() { return _mm_setzero_ps(); }
    static Value add(Value a, Value b) { return _mm_add_ps(a,b); }
    static Value mul(Value a, float b) { return _mm_mul_ps(a,_mm_set1_ps(b)); }
    static float alpha(Value a) { return _mm_cvtss_f32(_mm_shuffle_ps(a,a,_MM_SHUFFLE(3,3,3,3))); }
    static void store(Pixel* pixel, Value a) { _mm_storeu_ps(&pixel->r,a); }
};

template<class M>
typename M::Value lerp(typename M::Value a, typename M::Value b, float weight) {
    return M::add(M::mul(a,1-weight),M::mul(b,weight));
}

inline float coverage(const Layer& layer, int x, int y, float inverseWidth, float inverseHeight) {
    float dx = std::abs((x+.5f)*inverseWidth-.5f)/layer.radius;
    float dy = std::abs((y+.5f)*inverseHeight-.5f)/layer.radius;
    float distance = layer.mask == 1 ? std::sqrt(dx*dx+dy*dy) : std::max(dx,dy);
    return std::clamp((1-distance)/layer.feather,0.f,1.f);
}

template<class M>
void composite_rows(const Frame& frame, const Pixel* input, Pixel* output, unsigned begin, unsigned end) {
    const int width=frame.width, height=frame.height;
    const std::size_t pixels=std::size_t(width)*height;
    const float cx=(width-1)*.5f, cy=(height-1)*.5f, inverseWidth=1.f/width, inverseHeight=1.f/height;
    for (unsigned y=begin; y<end; ++y) {
        float offsetY[3];
        for (unsigned n=0; n<frame.layers; ++n) {
            const auto& layer=frame.layer[n];
            offsetY[n]=(y-cy-height*layer.y)/layer.scale;
        }
        for (int x=0; x<width; ++x) {
            auto result=M::zero();
            auto left=M::zero();
            for (unsigned n=0; n<frame.layers; ++n) {
                const auto& layer=frame.layer[n];
                const float dx=(x-cx-width*layer.x)/layer.scale, dy=offsetY[n];
                const float sx=cx+dx*layer.cosine+dy*layer.sine;
                const float sy=cy-dx*layer.sine+dy*layer.cosine;
                auto foreground=M::zero();
                if (sx>=-.5f && sy>=-.5f && sx<=width-.5f && sy<=height-.5f) {
                    const float u=std::clamp(sx,0.f,float(width-1)), v=std::clamp(sy,0.f,float(height-1));
                    const int x0=int(u), y0=int(v), x1=std::min(x0+1,width-1), y1=std::min(y0+1,height-1);
                    const Pixel* source=input+layer.slice*pixels;
                    const auto fetch=[&](int px,int py) {
                        const auto value=M::load(source+std::size_t(py)*width+px);
                        return layer.mask ? M::mul(value,coverage(layer,px,py,inverseWidth,inverseHeight)) : value;
                    };
                    foreground=M::mul(lerp<M>(lerp<M>(fetch(x0,y0),fetch(x1,y0),u-x0),
                                               lerp<M>(fetch(x0,y1),fetch(x1,y1),u-x0),v-y0),layer.opacity);
                }
                if (frame.dissolve>=0 && n<2) {
                    if (n==0) left=foreground;
                    else result=lerp<M>(left,foreground,frame.dissolve);
                } else {
                    result=M::add(M::mul(result,1-M::alpha(foreground)),foreground);
                }
            }
            M::store(output+std::size_t(y)*width+x,result);
        }
    }
}

class CpuCompositor {
    std::vector<std::thread> workers;
    std::mutex mutex;
    std::condition_variable work, completion;
    unsigned generation=0, active=0;
    bool stopping=false;
    Frame frame{};
    const Pixel* input=nullptr;
    Pixel* output=nullptr;

    void process(unsigned index, unsigned count) {
        unsigned seen=0;
        std::unique_lock<std::mutex> lock(mutex);
        while (true) {
            work.wait(lock,[&]{return stopping || generation!=seen;});
            if (stopping) return;
            seen=generation;
            lock.unlock();
            composite_rows<Math<true>>(frame,input,output,frame.height*index/count,frame.height*(index+1)/count);
            lock.lock();
            if (--active==0) completion.notify_one();
        }
    }

    void stop() {
        {
            std::lock_guard<std::mutex> lock(mutex);
            stopping=true;
        }
        work.notify_all();
        for (auto& worker:workers) worker.join();
    }

public:
    explicit CpuCompositor(unsigned count) {
        try {
            for (unsigned i=0; i<count; ++i) workers.emplace_back([this,i,count]{process(i,count);});
        } catch (...) {
            stop();
            throw;
        }
    }
    ~CpuCompositor() { stop(); }
    void render(const Frame& parameters, const Pixel* source, Pixel* picture) {
        if (workers.empty()) {
            composite_rows<Math<false>>(parameters,source,picture,0,parameters.height);
            return;
        }
        std::unique_lock<std::mutex> lock(mutex);
        frame=parameters;
        input=source;
        output=picture;
        active=unsigned(workers.size());
        ++generation;
        work.notify_all();
        completion.wait(lock,[&]{return active==0;});
    }
};

}
