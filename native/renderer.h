#pragma once
#include <dxgi1_6.h>
#include "sampler.h"
const char* nativeShader=R"HLSL(
Texture2DArray<float> Y:register(t0);Texture2DArray<float2> UV:register(t1);SamplerState S:register(s0);
cbuffer Params:register(b0){float4 geometry;float4 effect;float4 range;float4 source;float4 coefficients;}
struct Vertex {float4 pos:SV_Position;float2 uv:TEXCOORD0;};
Vertex vs(uint id:SV_VertexID){Vertex v;float2 q=float2((id<<1)&2,id&2);v.uv=q;v.pos=float4(q*float2(2,-2)+float2(-1,1),0,1);return v;}
float3 pq(float3 v){v=pow(max(v,0),1.0/78.84375);return pow(max(v-.8359375,0)/(18.8515625-18.6875*v),1.0/.1593017578125);}
float4 ps(Vertex v):SV_Target{
 float2 q=v.uv-geometry.xy;q.x*=source.w;
 q=float2(effect.x*q.x+effect.y*q.y,-effect.y*q.x+effect.x*q.y);q.x/=source.w;q=q/geometry.zw+.5;
 if(any(q<0)||any(q>1))discard;
 uint yw,yh,yl,uw,uh,ul;Y.GetDimensions(yw,yh,yl);UV.GetDimensions(uw,uh,ul);
 float2 yt=.5/float2(yw,yh),ut=.5/float2(uw,uh);
 float2 yq=clamp(q*source.xy,yt,source.xy-yt),uq=clamp(q*source.xy,ut,source.xy-ut);
 float y=(Y.Sample(S,float3(yq,0))-range.x)*range.y;
 float2 uv=(UV.Sample(S,float3(uq,0))-range.z)*range.w;
 float3 rgb=float3(y+coefficients.x*uv.y,y-coefficients.y*uv.x-coefficients.z*uv.y,y+coefficients.w*uv.x);
 if(source.z>.5){
  float3 c=pq(saturate(rgb))*125.0;
  rgb=float3(dot(c,float3(1.660491,-.587641,-.072850)),dot(c,float3(-.124550,1.132900,-.008350)),dot(c,float3(-.018151,-.100579,1.118730)));
 }else rgb=saturate(rgb);
 return float4(rgb,effect.z);
}
)HLSL";
struct DeviceLock {
 AVD3D11VADeviceContext* hw;
 DeviceLock(AVD3D11VADeviceContext* p):hw(p){hw->lock(hw->lock_ctx);}
 ~DeviceLock(){hw->unlock(hw->lock_ctx);}
};
struct NativeDisplay {
 HWND window=nullptr,parent=nullptr;Com<IDXGISwapChain> swap;Com<ID3D11RenderTargetView> target;
 ID3D11Device* device;Com<ID3D11PixelShader> pixel;int width=0,height=0;bool hdr=false;
 uint64_t calls=0;UINT displayed=0;bool statistics=false,wasVisible=false;
 static LRESULT CALLBACK proc(HWND w,UINT m,WPARAM a,LPARAM b){return DefWindowProcW(w,m,a,b);}
 NativeDisplay(ID3D11Device* d,HWND p,int w,int h,bool pq,decltype(&D3DCompile) compile):parent(p),device(d),hdr(pq){
  if(parent)SetThreadDpiAwarenessContext(GetWindowDpiAwarenessContext(parent));
  WNDCLASSW wc={};wc.lpfnWndProc=proc;wc.hInstance=GetModuleHandleW(nullptr);wc.lpszClassName=L"VlogCraftNativePlayback";RegisterClassW(&wc);
  window=CreateWindowW(wc.lpszClassName,L"VlogCraft native preview",p?WS_CHILD|WS_VISIBLE:WS_OVERLAPPEDWINDOW,0,0,w,h,p,nullptr,wc.hInstance,nullptr);
  if(!window)throw std::runtime_error("Native surface unavailable");ShowWindow(window,SW_SHOWNOACTIVATE);
  Com<IDXGIDevice> dxgi;Com<IDXGIAdapter> adapter;Com<IDXGIFactory> factory;
  check(d->QueryInterface(__uuidof(IDXGIDevice),(void**)dxgi.out()),"DXGI device");
  check(dxgi->GetAdapter(adapter.out()),"DXGI adapter");check(adapter->GetParent(__uuidof(IDXGIFactory),(void**)factory.out()),"DXGI factory");
  DXGI_SWAP_CHAIN_DESC desc={};desc.BufferDesc.Width=w;desc.BufferDesc.Height=h;
  desc.BufferDesc.Format=pq?DXGI_FORMAT_R16G16B16A16_FLOAT:DXGI_FORMAT_B8G8R8A8_UNORM;
  desc.SampleDesc.Count=1;desc.BufferUsage=DXGI_USAGE_RENDER_TARGET_OUTPUT;desc.BufferCount=3;desc.OutputWindow=window;desc.Windowed=TRUE;desc.SwapEffect=DXGI_SWAP_EFFECT_FLIP_DISCARD;
  check(factory->CreateSwapChain(d,&desc,swap.out()),"Native swap chain");
  if(pq){
   Com<IDXGIOutput> output;Com<IDXGIOutput6> advanced;DXGI_OUTPUT_DESC1 info={};
   check(swap->GetContainingOutput(output.out()),"Display output");
   check(output->QueryInterface(__uuidof(IDXGIOutput6),(void**)advanced.out()),"Advanced color detection");
   check(advanced->GetDesc1(&info),"Display color description");
   if(info.ColorSpace!=DXGI_COLOR_SPACE_RGB_FULL_G2084_NONE_P2020)throw std::runtime_error("HDR display is not active; select explicit SDR fallback");
   Com<IDXGISwapChain3> modern;check(swap->QueryInterface(__uuidof(IDXGISwapChain3),(void**)modern.out()),"scRGB swap chain");
   check(modern->SetColorSpace1(DXGI_COLOR_SPACE_RGB_FULL_G10_NONE_P709),"scRGB display color space");
  }
  const char* source="Texture2D<float4> image:register(t0);SamplerState s:register(s0);float4 display(float4 p:SV_Position,float2 uv:TEXCOORD0):SV_Target{return image.Sample(s,uv);}";
  Com<ID3DBlob> blob,error;check(compile(source,strlen(source),"display",nullptr,nullptr,"display","ps_5_0",D3DCOMPILE_OPTIMIZATION_LEVEL3,0,blob.out(),error.out()),"Display shader");
  check(d->CreatePixelShader(blob->GetBufferPointer(),blob->GetBufferSize(),nullptr,pixel.out()),"Display pixel shader");
  resize(nullptr,w,h);
 }
 void resize(ID3D11DeviceContext* context,int w,int h){
  if(w<2||h<2)return;if(w==width&&h==height)return;
  if(context)context->OMSetRenderTargets(0,nullptr,nullptr);target.out();
  if(width)check(swap->ResizeBuffers(0,w,h,DXGI_FORMAT_UNKNOWN,0),"Native surface resize");
  width=w;height=h;SetWindowPos(window,HWND_TOP,0,0,w,h,SWP_NOACTIVATE);
  Com<ID3D11Texture2D> back;check(swap->GetBuffer(0,__uuidof(ID3D11Texture2D),(void**)back.out()),"Native back buffer");
  check(device->CreateRenderTargetView(back,nullptr,target.out()),"Native display target");
 }
 bool needsResize()const{if(!parent)return false;RECT r={};GetClientRect(parent,&r);return r.right>=2&&r.bottom>=2&&(r.right!=width||r.bottom!=height||wasVisible!=(bool)IsWindowVisible(window));}
 void present(ID3D11DeviceContext* context,ID3D11ShaderResourceView* image){
  if(parent){RECT r={};GetClientRect(parent,&r);resize(context,r.right,r.bottom);}
  ID3D11RenderTargetView* rt=target;context->OMSetRenderTargets(1,&rt,nullptr);context->OMSetBlendState(nullptr,nullptr,0xffffffff);
  D3D11_VIEWPORT vp={0,0,(float)width,(float)height,0,1};context->RSSetViewports(1,&vp);
  context->PSSetShader(pixel,nullptr,0);context->PSSetShaderResources(0,1,&image);context->Draw(3,0);
  ID3D11ShaderResourceView* empty=nullptr;context->PSSetShaderResources(0,1,&empty);
 }
 void flip(){
  check(swap->Present(1,0),"Native Present");calls++;
  wasVisible=IsWindowVisible(window);stats();
 }
 void stats(){
  DXGI_FRAME_STATISTICS data={};if(SUCCEEDED(swap->GetFrameStatistics(&data))){statistics=true;displayed=data.PresentCount;}else statistics=false;
 }
 ~NativeDisplay(){if(window)DestroyWindow(window);}
};
struct Slot {
 Com<ID3D11Texture2D> image;Com<ID3D11RenderTargetView> target;Com<ID3D11ShaderResourceView> view;Com<ID3D11Query> query;
 bool pending=false;int64_t frame=-1,generation=-1;std::vector<Frame> holds;
};
struct Renderer {
 AVBufferRef* hw=nullptr;AVD3D11VADeviceContext* hd;ID3D11Device* device;ID3D11DeviceContext* context;
 HMODULE compiler=nullptr;Com<ID3D11VertexShader> vertex;Com<ID3D11PixelShader> pixel;
 Com<ID3D11Buffer> constants;Com<ID3D11SamplerState> sampler;Com<ID3D11BlendState> blend;
 Slot slots[3];Sampler textures;std::unique_ptr<NativeDisplay> display;uint64_t submitted=0,completed=0;int64_t completedFrame=-1,completedGeneration=-1;size_t peakPending=0;
 Renderer(const Plan& plan,HWND parent,bool offscreen){
  avcheck(av_hwdevice_ctx_create(&hw,AV_HWDEVICE_TYPE_D3D11VA,nullptr,nullptr,0),"D3D11 hardware");
  hd=(AVD3D11VADeviceContext*)((AVHWDeviceContext*)hw->data)->hwctx;hd->BindFlags|=D3D11_BIND_SHADER_RESOURCE;device=hd->device;context=hd->device_context;
  compiler=LoadLibraryW(L"d3dcompiler_47.dll");if(!compiler)throw std::runtime_error("Shader compiler missing");
  auto compile=(decltype(&D3DCompile))GetProcAddress(compiler,"D3DCompile");
  Com<ID3DBlob> vs,ps,error;check(compile(nativeShader,strlen(nativeShader),"native",nullptr,nullptr,"vs","vs_5_0",D3DCOMPILE_OPTIMIZATION_LEVEL3,0,vs.out(),error.out()),"Native vertex shader");
  check(compile(nativeShader,strlen(nativeShader),"native",nullptr,nullptr,"ps","ps_5_0",D3DCOMPILE_OPTIMIZATION_LEVEL3,0,ps.out(),error.out()),"Native pixel shader");
  check(device->CreateVertexShader(vs->GetBufferPointer(),vs->GetBufferSize(),nullptr,vertex.out()),"Native vertex");
  check(device->CreatePixelShader(ps->GetBufferPointer(),ps->GetBufferSize(),nullptr,pixel.out()),"Native pixel");
  D3D11_BUFFER_DESC bd={};bd.ByteWidth=sizeof(Parameters);bd.Usage=D3D11_USAGE_DEFAULT;bd.BindFlags=D3D11_BIND_CONSTANT_BUFFER;check(device->CreateBuffer(&bd,nullptr,constants.out()),"Native parameters");
  D3D11_SAMPLER_DESC sd={};sd.Filter=D3D11_FILTER_MIN_MAG_LINEAR_MIP_POINT;sd.AddressU=sd.AddressV=sd.AddressW=D3D11_TEXTURE_ADDRESS_CLAMP;sd.MaxLOD=D3D11_FLOAT32_MAX;check(device->CreateSamplerState(&sd,sampler.out()),"Native sampler");
  D3D11_BLEND_DESC b={};auto& t=b.RenderTarget[0];t.BlendEnable=true;t.SrcBlend=D3D11_BLEND_SRC_ALPHA;t.DestBlend=D3D11_BLEND_INV_SRC_ALPHA;t.BlendOp=D3D11_BLEND_OP_ADD;t.SrcBlendAlpha=D3D11_BLEND_ONE;t.DestBlendAlpha=D3D11_BLEND_ZERO;t.BlendOpAlpha=D3D11_BLEND_OP_ADD;t.RenderTargetWriteMask=D3D11_COLOR_WRITE_ENABLE_ALL;check(device->CreateBlendState(&b,blend.out()),"Native blend");
  for(auto& slot:slots){
   D3D11_TEXTURE2D_DESC d={};d.Width=plan.width;d.Height=plan.height;d.MipLevels=d.ArraySize=1;d.Format=DXGI_FORMAT_R16G16B16A16_FLOAT;d.SampleDesc.Count=1;d.BindFlags=D3D11_BIND_RENDER_TARGET|D3D11_BIND_SHADER_RESOURCE;
   check(device->CreateTexture2D(&d,nullptr,slot.image.out()),"Native float16 frame");
   check(device->CreateRenderTargetView(slot.image,nullptr,slot.target.out()),"Native float16 target");
   check(device->CreateShaderResourceView(slot.image,nullptr,slot.view.out()),"Native float16 view");
   D3D11_QUERY_DESC query={D3D11_QUERY_EVENT,0};check(device->CreateQuery(&query,slot.query.out()),"Native completion query");
  }
  if(!offscreen)display=std::make_unique<NativeDisplay>(device,parent,plan.width,plan.height,plan.hdr,compile);
 }
 Slot* available(){
  DeviceLock lock(hd);Slot* free=nullptr;for(auto& slot:slots){
   if(slot.pending){BOOL done=false;HRESULT result=context->GetData(slot.query,&done,sizeof(done),D3D11_ASYNC_GETDATA_DONOTFLUSH);check(result,"Native GPU completion");
    if(result==S_OK){slot.pending=false;slot.holds.clear();completed++;
     if(slot.generation>completedGeneration){completedGeneration=slot.generation;completedFrame=slot.frame;}else if(slot.generation==completedGeneration)completedFrame=std::max(completedFrame,slot.frame);}}
   if(!slot.pending&&!free)free=&slot;
  }return free;
 }
 void drain(){auto start=Clock::now();while(true){available();bool pending=false;for(auto& s:slots)pending|=s.pending;if(!pending)return;if(seconds(start)>5)throw std::runtime_error("Native GPU completion timeout");Sleep(1);}}
 void draw(Slot& slot,const Plan& plan,int64_t frame,int64_t gen,const std::vector<std::pair<const Clip*,Frame>>& layers){
  {DeviceLock lock(hd);float clear[4]={plan.hdr?0.f:16.f/255,plan.hdr?0.f:19.f/255,plan.hdr?0.f:26.f/255,1};context->ClearRenderTargetView(slot.target,clear);
  ID3D11RenderTargetView* rt=slot.target;context->OMSetRenderTargets(1,&rt,nullptr);context->OMSetBlendState(blend,nullptr,0xffffffff);
  D3D11_VIEWPORT vp={0,0,(float)plan.width,(float)plan.height,0,1};context->RSSetViewports(1,&vp);context->IASetPrimitiveTopology(D3D11_PRIMITIVE_TOPOLOGY_TRIANGLELIST);
  context->VSSetShader(vertex,nullptr,0);context->PSSetShader(pixel,nullptr,0);ID3D11SamplerState* samp=sampler;context->PSSetSamplers(0,1,&samp);ID3D11Buffer* cb=constants;context->PSSetConstantBuffers(0,1,&cb);
  for(auto& layer:layers){
   auto& c=*layer.first;AVFrame* f=layer.second.get();
   bool pq=f->color_trc==AVCOL_TRC_SMPTE2084&&f->colorspace==AVCOL_SPC_BT2020_NCL;
   if(pq!=plan.hdr||f->color_trc==AVCOL_TRC_ARIB_STD_B67)throw std::runtime_error("Native color contract changed");
   double src=plan.sourceTick(c,frame)*av_q2d(c.timebase);
   double angle=(c.value("rotation",src,c.rotation)-c.sourceRotation)*3.141592653589793/180;
   bool portrait=std::abs((int)std::round(c.sourceRotation))%180==90;
   double sar=f->sample_aspect_ratio.num?av_q2d(f->sample_aspect_ratio):1;
   double codedW=f->width*sar,codedH=f->height,displayW=portrait?codedH:codedW,displayH=portrait?codedW:codedH;
   double fit=c.cover?std::max(plan.width/displayW,plan.height/displayH):std::min(plan.width/displayW,plan.height/displayH);
   double scale=c.value("scale",src,c.scale),local=(frame-c.position)*av_q2d(av_inv_q(plan.rate)),remaining=(c.end-frame)*av_q2d(av_inv_q(plan.rate));
   Parameters p={};p.geometry[0]=.5f+c.value("x",src,c.x);p.geometry[1]=.5f+c.value("y",src,c.y);
   p.geometry[2]=codedW*fit*scale/plan.width;p.geometry[3]=codedH*fit*scale/plan.height;
   p.effect[0]=cos(angle);p.effect[1]=sin(angle);p.effect[2]=c.value("opacity",src,c.opacity)*std::min(c.fadeIn>0?std::min(1.,local/c.fadeIn):1.,c.fadeOut>0?std::min(1.,remaining/c.fadeOut):1.);
   auto view=textures.texture(f,device,context,false,p.source,p.range);p.source[2]=plan.hdr?1:0;p.source[3]=(float)plan.width/plan.height;
   const float a[4]={1.5748f,.187324f,.468124f,1.8556f},b[4]={1.402f,.344136f,.714136f,1.772f},h[4]={1.4746f,.164553f,.571353f,1.8814f};
   memcpy(p.matrix,plan.hdr?h:f->colorspace==AVCOL_SPC_BT709?a:b,sizeof(p.matrix));
   ID3D11ShaderResourceView* srv[2]={view.first,view.second};context->PSSetShaderResources(0,2,srv);context->UpdateSubresource(constants,0,nullptr,&p,0,0);context->Draw(3,0);
   ID3D11ShaderResourceView* empty[2]={};context->PSSetShaderResources(0,2,empty);slot.holds.push_back(layer.second);
  }
  if(display)display->present(context,slot.view);
  context->End(slot.query);context->Flush();slot.pending=true;slot.frame=frame;slot.generation=gen;submitted++;
  size_t pending=0;for(auto& s:slots)pending+=s.pending;peakPending=std::max(peakPending,pending);}
  if(display)display->flip();
 }
 void capture(Slot& slot,const std::string& path){
  drain();DeviceLock lock(hd);D3D11_TEXTURE2D_DESC d;slot.image->GetDesc(&d);d.BindFlags=0;d.Usage=D3D11_USAGE_STAGING;d.CPUAccessFlags=D3D11_CPU_ACCESS_READ;
  Com<ID3D11Texture2D> cpu;check(device->CreateTexture2D(&d,nullptr,cpu.out()),"Native capture");context->CopyResource(cpu,slot.image);
  D3D11_MAPPED_SUBRESOURCE m;check(context->Map(cpu,0,D3D11_MAP_READ,0,&m),"Native readback");
  std::ofstream out(std::filesystem::u8path(path),std::ios::binary);for(UINT y=0;y<d.Height;y++)out.write((char*)m.pData+y*m.RowPitch,d.Width*8);context->Unmap(cpu,0);
 }
 ~Renderer(){display.reset();if(context)context->ClearState();textures.clear();if(hw)av_buffer_unref(&hw);if(compiler)FreeLibrary(compiler);}
};
