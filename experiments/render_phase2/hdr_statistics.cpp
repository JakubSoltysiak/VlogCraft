// Exact unsigned 16-bit MaxRGB histogram for decoded planar GBR pictures.
#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <emmintrin.h>
#include <vector>

namespace {
constexpr std::size_t codes=65536;
constexpr std::size_t shards=4;

__m128i maximum(__m128i a,__m128i b) {
    return _mm_add_epi16(b,_mm_subs_epu16(a,b));
}
}

extern "C" __declspec(dllexport) int hdr_maxrgb_histogram(
        const std::uint16_t* gbr,std::size_t pixels,std::int64_t* histogram,std::uint16_t* maxima) noexcept {
    if(!gbr || !histogram || !maxima || !pixels || pixels>7680u*4320u) return 0;
    try {
        thread_local std::vector<std::uint32_t> scratch(codes*shards);
        std::fill(scratch.begin(),scratch.end(),0);
        const auto* blue=gbr+pixels;
        const auto* red=blue+pixels;
        __m128i maxGreen=_mm_setzero_si128(),maxBlue=maxGreen,maxRed=maxGreen;
        std::size_t i=0;
        alignas(16) std::uint16_t peaks[8];
        for(;i+8<=pixels;i+=8) {
            const auto g=_mm_loadu_si128(reinterpret_cast<const __m128i*>(gbr+i));
            const auto b=_mm_loadu_si128(reinterpret_cast<const __m128i*>(blue+i));
            const auto r=_mm_loadu_si128(reinterpret_cast<const __m128i*>(red+i));
            maxGreen=maximum(maxGreen,g);
            maxBlue=maximum(maxBlue,b);
            maxRed=maximum(maxRed,r);
            _mm_store_si128(reinterpret_cast<__m128i*>(peaks),maximum(maximum(g,b),r));
            for(std::size_t k=0;k<8;++k)
                ++scratch[(k%shards)*codes+peaks[k]];
        }
        const __m128i channels[]={maxGreen,maxBlue,maxRed};
        for(unsigned c=0;c<3;++c) {
            _mm_store_si128(reinterpret_cast<__m128i*>(peaks),channels[c]);
            maxima[c]=*std::max_element(peaks,peaks+8);
        }
        for(;i<pixels;++i) {
            const auto g=gbr[i],b=blue[i],r=red[i];
            maxima[0]=std::max(maxima[0],g);
            maxima[1]=std::max(maxima[1],b);
            maxima[2]=std::max(maxima[2],r);
            ++scratch[std::max({g,b,r})];
        }
        for(std::size_t k=0;k<codes;++k)
            histogram[k]=scratch[k]+scratch[codes+k]+scratch[2*codes+k]+scratch[3*codes+k];
        return 1;
    } catch(...) {
        return 0;
    }
}
