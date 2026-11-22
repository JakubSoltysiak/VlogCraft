#pragma once

namespace render_phase2 {

inline const char* pq_shader_source=R"HLSL(
Texture2D<float4> linearPicture : register(t2);
RWByteAddressBuffer planes : register(u0);

// One group covers 32 by 16 luma samples with the chroma filter's halo.
groupshared float3 tile[18][33];

float3 pq(float3 rgb) {
    // The compositor uses 1.0 for 100 cd/m^2. ST 2084 uses 10,000 cd/m^2.
    float3 intensity=pow(saturate(rgb*.01),653.0/4096.0);
    return pow((3424.0/4096.0+(2413.0/128.0)*intensity)/
               (1.0+(2392.0/128.0)*intensity),2523.0/32.0);
}

float3 toYuv(float3 rgb) {
    float y=dot(rgb,float3(.2627,.6780,.0593));
    return float3(y,(rgb.b-y)/1.8814,(rgb.r-y)/1.4746);
}

uint quantize(float value,uint2 at,uint low,uint high) {
    // Ordered, zero-mean dither. The zimg reference uses serial error diffusion.
    static const uint bayer[16]={0,8,2,10,12,4,14,6,3,11,1,9,15,7,13,5};
    float dither=(float(bayer[(at.y%4)*4+at.x%4])+.5)/16.0-.5;
    return (uint)clamp(round(value+dither),float(low),float(high));
}

uint luma(float y,uint2 at) {
    return quantize(64.0+876.0*y,at,64,940);
}

float2 horizontal(uint y,uint x) {
    return .25*tile[y][x-1].yz+.5*tile[y][x].yz+.25*tile[y][x+1].yz;
}

float2 chroma(uint y,uint x) {
    // Bilinear decimation, horizontally left-sited and vertically centered.
    return .125*horizontal(y-1,x)+.375*horizontal(y,x)+
           .375*horizontal(y+1,x)+.125*horizontal(y+2,x);
}

[numthreads(8,8,1)]
void main(uint3 group : SV_GroupID,uint3 thread : SV_GroupThreadID,uint index : SV_GroupIndex) {
    uint width,height;
    linearPicture.GetDimensions(width,height);
    const uint2 origin=group.xy*uint2(32,16);
    for(uint i=index;i<18*33;i+=64) {
        uint2 local=uint2(i%33,i/33);
        int2 samplePoint=clamp(int2(origin+local)-1,int2(0,0),int2(width,height)-1);
        tile[local.y][local.x]=toYuv(pq(linearPicture.Load(int3(samplePoint,0)).rgb));
    }
    GroupMemoryBarrierWithGroupSync();

    uint2 at=origin+thread.xy*uint2(4,2);
    if(at.x>=width || at.y>=height) return;
    uint2 pos=thread.xy*uint2(4,2)+1;
    for(uint row=0;row<2;++row) {
        uint2 here=at+uint2(0,row);
        for(uint pair=0;pair<4;pair+=2) {
            uint a=luma(tile[pos.y+row][pos.x+pair].x,here+uint2(pair,0));
            uint b=luma(tile[pos.y+row][pos.x+pair+1].x,here+uint2(pair+1,0));
            planes.Store(2*(here.y*width+here.x+pair),a|(b<<16));
        }
    }
    float2 first=chroma(pos.y,pos.x);
    float2 second=chroma(pos.y,pos.x+2);
    uint2 address=at/2;
    uint u0=quantize(512.0+896.0*first.x,address,64,960);
    uint u1=quantize(512.0+896.0*second.x,address+uint2(1,0),64,960);
    uint v0=quantize(512.0+896.0*first.y,address,64,960);
    uint v1=quantize(512.0+896.0*second.y,address+uint2(1,0),64,960);
    uint bytes=2*width*height;
    uint offset=2*(address.y*(width/2)+address.x);
    planes.Store(bytes+offset,u0|(u1<<16));
    planes.Store(bytes+bytes/4+offset,v0|(v1<<16));
}
)HLSL";

}
