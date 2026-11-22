#pragma once

#include <algorithm>
#include <cmath>
#include <condition_variable>
#include <cstdint>
#include <cstring>
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
    Layer layer[8];
    std::uint32_t project;
    float white;
    std::uint32_t reserved[2];
};

constexpr unsigned layerBudget=8;
constexpr unsigned legacyLayerBudget=3;
constexpr unsigned legacyFrameSize=160;
static_assert(sizeof(Pixel)==16 && sizeof(Layer)==48 && sizeof(Frame)==416);

struct Geometry {
    double scale, cosine, sine, x, y;
};

struct RowRange {
    std::uint32_t start, end;
};

// Compute hard canvas coverage in double precision. Both processors keep
// float32 bilinear taps, but they use the same inclusive/exclusive edge.
inline void prepare_ranges(const Frame& frame,const Geometry* geometry,RowRange* ranges) {
    const int width=frame.width,height=frame.height;
    const double cx=(width-1)*.5,cy=(height-1)*.5;
    for(unsigned n=0;n<frame.layers;++n) {
        const auto& g=geometry[n];
        for(int y=0;y<height;++y) {
            const double dy=(y-cy-height*g.y)/g.scale;
            const double dx=(-cx-width*g.x)/g.scale;
            double low=0,high=width-1;
            const auto intersect=[&](double base,double slope,double limit) {
                if(slope==0) {
                    if(base<-.5 || base>limit) { low=1; high=0; }
                    return;
                }
                const double a=(-.5-base)/slope, b=(limit-base)/slope;
                low=std::max(low,std::min(a,b));
                high=std::min(high,std::max(a,b));
            };
            intersect(cx+dx*g.cosine+dy*g.sine,g.cosine/g.scale,width-.5);
            intersect(cy-dx*g.sine+dy*g.cosine,-g.sine/g.scale,height-.5);
            auto& range=ranges[n*height+y];
            range={0,0};
            if(low>high+1e-8) continue;
            const auto contains=[&](int x) {
                const double local=(x-cx-width*g.x)/g.scale;
                const double sx=cx+local*g.cosine+dy*g.sine;
                const double sy=cy-local*g.sine+dy*g.cosine;
                return sx>=-.5 && sy>=-.5 && sx<=width-.5 && sy<=height-.5;
            };
            // Correct only the rounded boundary samples using the original
            // expression order rather than relying on its rearrangement.
            int first=std::clamp(int(std::ceil(low-1e-8)),0,width-1);
            int last=std::clamp(int(std::floor(high+1e-8)),0,width-1);
            if(first<=last && !contains(first)) ++first;
            if(first<=last && !contains(last)) --last;
            if(first<=last) range={unsigned(first),unsigned(last+1)};
        }
    }
}

template<bool Simd> struct Math;

template<> struct Math<false> {
    using Value = Pixel;
    static Value load(const Pixel* pixel) { return *pixel; }
    static Value zero() { return {}; }
    static Value opaque(float v) { return {v,v,v,1}; }
    static Value add(Value a, Value b) { return {a.r+b.r,a.g+b.g,a.b+b.b,a.a+b.a}; }
    static Value mul(Value a, float b) { return {a.r*b,a.g*b,a.b*b,a.a*b}; }
    static Value gain(Value a, float b) { return {a.r*b,a.g*b,a.b*b,a.a}; }
    static float alpha(Value a) { return a.a; }
    static void store(Pixel* pixel, Value a) { *pixel = a; }
};

template<> struct Math<true> {
    using Value = __m128;
    static Value load(const Pixel* pixel) { return _mm_loadu_ps(&pixel->r); }
    static Value zero() { return _mm_setzero_ps(); }
    static Value opaque(float v) { return _mm_set_ps(1,v,v,v); }
    static Value add(Value a, Value b) { return _mm_add_ps(a,b); }
    static Value mul(Value a, float b) { return _mm_mul_ps(a,_mm_set1_ps(b)); }
    static Value gain(Value a, float b) { return _mm_mul_ps(a,_mm_set_ps(1,b,b,b)); }
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
void composite_rows(const Frame& frame,const RowRange* ranges,const Pixel* input,Pixel* output,
                    unsigned begin,unsigned end) {
    const int width=frame.width, height=frame.height;
    const std::size_t pixels=std::size_t(width)*height;
    const float cx=(width-1)*.5f, cy=(height-1)*.5f, inverseWidth=1.f/width, inverseHeight=1.f/height;
    for (unsigned y=begin; y<end; ++y) {
        float offsetY[layerBudget];
        for (unsigned n=0; n<frame.layers; ++n) {
            const auto& layer=frame.layer[n];
            offsetY[n]=(y-cy-height*layer.y)/layer.scale;
        }
        for (int x=0; x<width; ++x) {
            auto result=frame.project?M::opaque(0):M::zero();
            auto left=M::zero();
            for (unsigned n=0; n<frame.layers; ++n) {
                const auto& layer=frame.layer[n];
                const float dx=(x-cx-width*layer.x)/layer.scale, dy=offsetY[n];
                const float sx=cx+dx*layer.cosine+dy*layer.sine;
                const float sy=cy-dx*layer.sine+dy*layer.cosine;
                auto foreground=M::zero();
                const auto& range=ranges[n*height+y];
                if (unsigned(x)>=range.start && unsigned(x)<range.end) {
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
                if(frame.project) {
                    float gain;
                    std::memcpy(&gain,&layer.reserved2,sizeof(gain));
                    foreground=M::gain(foreground,gain);
                    const auto picture=M::add(M::mul(result,1-M::alpha(foreground)),foreground);
                    if(layer.reserved1==1) left=picture;
                    else if(layer.reserved1==2) result=lerp<M>(left,picture,frame.dissolve);
                    else if(layer.reserved1>=3) {
                        const auto matte=M::opaque(layer.reserved1==4?frame.white:0);
                        const float mix=frame.dissolve*2;
                        result=mix<1?lerp<M>(left,matte,mix):lerp<M>(matte,picture,mix-1);
                    } else result=picture;
                } else if (frame.dissolve>=0 && n<2) {
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
    const RowRange* ranges=nullptr;
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
            composite_rows<Math<true>>(frame,ranges,input,output,frame.height*index/count,frame.height*(index+1)/count);
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
    void render(const Frame& parameters,const RowRange* coverage,const Pixel* source,Pixel* picture) {
        if (workers.empty()) {
            composite_rows<Math<false>>(parameters,coverage,source,picture,0,parameters.height);
            return;
        }
        std::unique_lock<std::mutex> lock(mutex);
        frame=parameters;
        ranges=coverage;
        input=source;
        output=picture;
        active=unsigned(workers.size());
        ++generation;
        work.notify_all();
        completion.wait(lock,[&]{return active==0;});
    }
};

}
