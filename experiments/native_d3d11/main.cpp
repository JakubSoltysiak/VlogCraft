#include "../../native/media.h"
#include "presentation.h"
int main(int argc,char**argv){
    try{
        int frames=180,width=960,height=540;bool present=false;HWND parent=nullptr;double seekAt=0;std::string mode="hardware",capture;std::vector<std::string> inputs;
        for(int i=1;i<argc;i++){std::string a=argv[i];if(a=="--frames")frames=atoi(argv[++i]);else if(a=="--width")width=atoi(argv[++i]);else if(a=="--height")height=atoi(argv[++i]);else if(a=="--mode")mode=argv[++i];else if(a=="--capture")capture=argv[++i];else if(a=="--seek")seekAt=atof(argv[++i]);else if(a=="--present")present=true;else if(a=="--parent")parent=(HWND)(uintptr_t)strtoull(argv[++i],nullptr,10);else inputs.push_back(a);}
        if(mode!="hardware"&&mode!="software"&&mode!="download")throw std::runtime_error("Choose hardware, software or download mode");
        if(inputs.empty()||inputs.size()>3||frames<1||width<2||height<2)throw std::runtime_error("one to three inputs, positive dimensions/frames required");
        av_log_set_level(AV_LOG_ERROR);auto start=Clock::now();
        AVBufferRef* hw=nullptr;avcheck(av_hwdevice_ctx_create(&hw,AV_HWDEVICE_TYPE_D3D11VA,nullptr,nullptr,0),"D3D11 device");
        auto hd=(AVD3D11VADeviceContext*)((AVHWDeviceContext*)hw->data)->hwctx;hd->BindFlags|=D3D11_BIND_SHADER_RESOURCE;
        ID3D11Device* device=hd->device;ID3D11DeviceContext* context=hd->device_context;
        HMODULE compiler=LoadLibraryW(L"d3dcompiler_47.dll");if(!compiler)throw std::runtime_error("Windows shader compiler unavailable");
        auto compile=(decltype(&D3DCompile))GetProcAddress(compiler,"D3DCompile");if(!compile)throw std::runtime_error("D3DCompile unavailable");
        Com<ID3DBlob> vsblob,psblob,error;
        check(compile(shader,strlen(shader),"prototype",nullptr,nullptr,"vs","vs_5_0",D3DCOMPILE_OPTIMIZATION_LEVEL3,0,vsblob.out(),error.out()),"vertex compile");
        HRESULT hr=compile(shader,strlen(shader),"prototype",nullptr,nullptr,"ps","ps_5_0",D3DCOMPILE_OPTIMIZATION_LEVEL3,0,psblob.out(),error.out());
        if(FAILED(hr)&&error.p)std::cerr<<(const char*)error->GetBufferPointer()<<std::endl;check(hr,"pixel compile");
        Com<ID3D11VertexShader> vs;Com<ID3D11PixelShader> ps;Com<ID3D11Buffer> constants;Com<ID3D11SamplerState> sampler;Com<ID3D11BlendState> blend;
        check(device->CreateVertexShader(vsblob->GetBufferPointer(),vsblob->GetBufferSize(),nullptr,vs.out()),"vertex shader");
        check(device->CreatePixelShader(psblob->GetBufferPointer(),psblob->GetBufferSize(),nullptr,ps.out()),"pixel shader");
        D3D11_BUFFER_DESC bd={};bd.ByteWidth=sizeof(Parameters);bd.Usage=D3D11_USAGE_DEFAULT;bd.BindFlags=D3D11_BIND_CONSTANT_BUFFER;check(device->CreateBuffer(&bd,nullptr,constants.out()),"constants");
        D3D11_SAMPLER_DESC sd={};sd.Filter=D3D11_FILTER_MIN_MAG_LINEAR_MIP_POINT;sd.AddressU=sd.AddressV=sd.AddressW=D3D11_TEXTURE_ADDRESS_CLAMP;sd.MaxLOD=D3D11_FLOAT32_MAX;check(device->CreateSamplerState(&sd,sampler.out()),"sampler");
        D3D11_BLEND_DESC blendDesc={};auto& blendRT=blendDesc.RenderTarget[0];blendRT.BlendEnable=true;blendRT.SrcBlend=D3D11_BLEND_SRC_ALPHA;blendRT.DestBlend=D3D11_BLEND_INV_SRC_ALPHA;blendRT.BlendOp=D3D11_BLEND_OP_ADD;blendRT.SrcBlendAlpha=D3D11_BLEND_ONE;blendRT.DestBlendAlpha=D3D11_BLEND_ZERO;blendRT.BlendOpAlpha=D3D11_BLEND_OP_ADD;blendRT.RenderTargetWriteMask=D3D11_COLOR_WRITE_ENABLE_ALL;
        check(device->CreateBlendState(&blendDesc,blend.out()),"blend");
        D3D11_TEXTURE2D_DESC td={};td.Width=width;td.Height=height;td.MipLevels=td.ArraySize=1;td.Format=DXGI_FORMAT_R16G16B16A16_FLOAT;td.SampleDesc.Count=1;td.BindFlags=D3D11_BIND_RENDER_TARGET|D3D11_BIND_SHADER_RESOURCE;
        Com<ID3D11Texture2D> output;Com<ID3D11RenderTargetView> target;check(device->CreateTexture2D(&td,nullptr,output.out()),"float16 output");check(device->CreateRenderTargetView(output,nullptr,target.out()),"render view");
        Com<ID3D11Query> complete;D3D11_QUERY_DESC qd={D3D11_QUERY_EVENT,0};check(device->CreateQuery(&qd,complete.out()),"fence");
        std::unique_ptr<Display> display;if(present)display=std::make_unique<Display>(device,output,width,height,parent,compile);
        std::vector<std::unique_ptr<Decoder>> decoders;for(auto& file:inputs)decoders.push_back(std::make_unique<Decoder>(file,hw,mode!="software"));
        double inputRate=av_q2d(decoders[0]->file->streams[decoders[0]->stream]->avg_frame_rate);
        if(present&&inputRate<=0)throw std::runtime_error("Presentation requires a known frame rate");
        double setup=seconds(start),first=0,draw=0,wait=0,seekTime=0;int rendered=0;
        if(seekAt>0){auto t=Clock::now();for(auto& d:decoders)d->seek(seekAt);seekTime=seconds(t);}
        auto run=Clock::now(),presentationOrigin=run;int late=0;
        for(int n=0;n<frames;n++){
            bool ok=true;for(auto& d:decoders)if(!(n==0&&seekAt>0)&&!d->next()){ok=false;break;}if(!ok)break;
            auto drawStart=Clock::now();float clear[4]={16.f/255,19.f/255,26.f/255,1};context->ClearRenderTargetView(target,clear);
            ID3D11RenderTargetView* rt=target;context->OMSetRenderTargets(1,&rt,nullptr);context->OMSetBlendState(blend,nullptr,0xffffffff);
            D3D11_VIEWPORT vp={0,0,(float)width,(float)height,0,1};context->RSSetViewports(1,&vp);context->IASetPrimitiveTopology(D3D11_PRIMITIVE_TOPOLOGY_TRIANGLELIST);
            context->VSSetShader(vs,nullptr,0);context->PSSetShader(ps,nullptr,0);ID3D11SamplerState* samp=sampler;context->PSSetSamplers(0,1,&samp);ID3D11Buffer* cb=constants;context->PSSetConstantBuffers(0,1,&cb);
            for(size_t i=0;i<decoders.size();i++){
                Parameters p={};p.geometry[0]=.5f+(i==1?-.2f:i==2?.2f:0);p.geometry[1]=.5f;p.geometry[2]=p.geometry[3]=i?.5f:1.f;
                p.effect[0]=1;p.effect[1]=0;p.effect[2]=i?.75f:1;p.effect[3]=0;
                auto view=decoders[i]->texture(device,context,mode=="download",p.source,p.range);
                auto f=decoders[i]->frame;
                if(f->color_trc==AVCOL_TRC_SMPTE2084||f->color_trc==AVCOL_TRC_ARIB_STD_B67||f->colorspace==AVCOL_SPC_BT2020_NCL)throw std::runtime_error("HDR/BT2020 transforms are not qualified in this prototype");
                const float bt709[4]={1.5748f,.187324f,.468124f,1.8556f},bt601[4]={1.402f,.344136f,.714136f,1.772f};
                memcpy(p.matrix,f->colorspace==AVCOL_SPC_BT709?bt709:bt601,sizeof(p.matrix));
                ID3D11ShaderResourceView* srv[2]={view.first,view.second};context->PSSetShaderResources(0,2,srv);
                context->UpdateSubresource(constants,0,nullptr,&p,0,0);context->Draw(3,0);
                ID3D11ShaderResourceView* empty[2]={};context->PSSetShaderResources(0,2,empty);
            }
            draw+=seconds(drawStart);auto waiting=Clock::now();context->End(complete);context->Flush();BOOL done=false;
            while(context->GetData(complete,&done,sizeof(done),0)==S_FALSE){if(seconds(waiting)>30)throw std::runtime_error("GPU fence timeout");Sleep(0);}
            wait+=seconds(waiting);rendered++;
            if(n==0){first=setup+seekTime+seconds(run);presentationOrigin=Clock::now();}
            if(display){
                auto targetTime=presentationOrigin+std::chrono::duration_cast<Clock::duration>(std::chrono::duration<double>(n/inputRate));
                if(Clock::now()>targetTime+std::chrono::duration<double>(1/inputRate))late++;
                std::this_thread::sleep_until(targetTime);display->present(context);
                if(n==0)presentationOrigin=Clock::now();
            }
            if(!capture.empty()&&(n==0||n==frames-1)){
                auto st=td;st.BindFlags=0;st.Usage=D3D11_USAGE_STAGING;st.CPUAccessFlags=D3D11_CPU_ACCESS_READ;Com<ID3D11Texture2D> cpu;check(device->CreateTexture2D(&st,nullptr,cpu.out()),"capture texture");
                context->CopyResource(cpu,output);D3D11_MAPPED_SUBRESOURCE map;check(context->Map(cpu,0,D3D11_MAP_READ,0,&map),"capture read");
                std::ofstream f(capture+"-"+std::to_string(n)+".rgba16f",std::ios::binary);
                for(int y=0;y<height;y++)f.write((char*)map.pData+y*map.RowPitch,width*8);context->Unmap(cpu,0);
            }
        }
        double elapsed=seconds(run);double decode=0,transfer=0,upload=0;for(auto& d:decoders){decode+=d->decode_s;transfer+=d->transfer_s;upload+=d->upload_s;}
        std::cout<<"{\"mode\":\""<<mode<<"\",\"layers\":"<<inputs.size()<<",\"width\":"<<width<<",\"height\":"<<height
                 <<",\"frames\":"<<rendered<<",\"setup_seconds\":"<<setup<<",\"first_frame_seconds\":"<<first<<",\"seek_seconds\":"<<seekTime
                 <<",\"processing_seconds\":"<<elapsed<<",\"composited_fps\":"<<rendered/elapsed<<",\"decode_api_seconds\":"<<decode
                 <<",\"transfer_seconds\":"<<transfer<<",\"upload_seconds\":"<<upload<<",\"draw_submit_seconds\":"<<draw<<",\"gpu_wait_seconds\":"<<wait
                 <<",\"float16_output\":true,\"presentation_enabled\":"<<(present?"true":"false")<<",\"present_calls\":"<<(display?display->calls:0)<<",\"late_frames\":"<<late<<",\"dxgi_statistics_available\":"<<(display&&display->statistics?"true":"false")<<",\"dxgi_present_count\":"<<(display?display->displayed:0)<<",\"present_call_fps_after_first\":"<<(display?display->callRate():0)<<",\"dxgi_present_rate\":"<<(display?display->displayRate():0)<<",\"present_wait_seconds\":"<<(display?display->presentWait:0)<<",\"audio\":false}"<<std::endl;
        
        decoders.clear();context->ClearState();av_buffer_unref(&hw);
        return rendered==frames?0:2;
    }catch(const std::exception& e){std::cerr<<e.what()<<std::endl;return 1;}
}
