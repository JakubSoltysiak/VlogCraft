#pragma once
struct Sampler {
AVFrame* host=av_frame_alloc();SwsContext* scaler=nullptr;std::vector<unsigned char> packed;Com<ID3D11Texture2D> uploaded;bool direct=false;double transfer_s=0,upload_s=0;
std::map<std::pair<ID3D11Texture2D*,int>,std::pair<ID3D11ShaderResourceView*,ID3D11ShaderResourceView*>> views;
std::map<ID3D11Texture2D*,uint64_t> pools;
uint64_t estimatedBytes()const{uint64_t total=0;for(auto& p:pools)total+=p.second;return total;}
void clear(){for(auto& v:views){v.second.first->Release();v.second.second->Release();}views.clear();pools.clear();uploaded.out();}
~Sampler(){clear();av_frame_free(&host);sws_freeContext(scaler);}
    std::pair<ID3D11ShaderResourceView*,ID3D11ShaderResourceView*> texture(AVFrame* frame,ID3D11Device* device,ID3D11DeviceContext* context,bool download,float* uvscale,float* range){
        AVFrame* src=frame;ID3D11Texture2D* tex=nullptr;int slice=0;
        if(frame->format==AV_PIX_FMT_D3D11&&!download){
            tex=(ID3D11Texture2D*)frame->data[0];slice=(int)(intptr_t)frame->data[1];direct=true;
        }else{
            auto start=Clock::now();
            if(frame->format==AV_PIX_FMT_D3D11){av_frame_unref(host);avcheck(av_hwframe_transfer_data(host,frame,0),"hardware download");src=host;}
            transfer_s+=seconds(start);start=Clock::now();
            // Transfer controls preserve source depth; no mandatory 8-bit intermediate.
            const AVPixFmtDescriptor* format=av_pix_fmt_desc_get((AVPixelFormat)src->format);
            bool high=format&&format->comp[0].depth>8;int bytes=high?2:1;
            AVPixelFormat packedFormat=high?AV_PIX_FMT_P010LE:AV_PIX_FMT_NV12;
            packed.resize((size_t)src->width*src->height*3/2*bytes);
            scaler=sws_getCachedContext(scaler,src->width,src->height,(AVPixelFormat)src->format,src->width,src->height,packedFormat,SWS_BILINEAR,nullptr,nullptr,nullptr);
            if(!scaler)throw std::runtime_error("sws allocation");
            uint8_t* dst[4]={packed.data(),packed.data()+(size_t)src->width*src->height*bytes,nullptr,nullptr};int pitch[4]={src->width*bytes,src->width*bytes,0,0};
            sws_scale(scaler,src->data,src->linesize,0,src->height,dst,pitch);
            if(!uploaded.p){D3D11_TEXTURE2D_DESC d={};d.Width=src->width;d.Height=src->height;d.MipLevels=1;d.ArraySize=1;d.Format=high?DXGI_FORMAT_P010:DXGI_FORMAT_NV12;d.SampleDesc.Count=1;d.BindFlags=D3D11_BIND_SHADER_RESOURCE;
                check(device->CreateTexture2D(&d,nullptr,uploaded.out()),"upload texture");}
            tex=uploaded.p;context->UpdateSubresource(tex,0,nullptr,packed.data(),src->width*bytes,0);
            upload_s+=seconds(start);
        }
        D3D11_TEXTURE2D_DESC desc;tex->GetDesc(&desc);
        uvscale[0]=(float)frame->width/desc.Width;uvscale[1]=(float)frame->height/desc.Height;
        bool ten=desc.Format==DXGI_FORMAT_P010;
        if(desc.Format!=DXGI_FORMAT_NV12&&!ten)throw std::runtime_error("only NV12/P010 implemented");
        range[0]=ten?4096.f/65535:16.f/255;range[1]=ten?65535.f/56064:255.f/219;
        range[2]=ten?32768.f/65535:128.f/255;range[3]=ten?65535.f/57344:255.f/224;
        if(frame->color_range==AVCOL_RANGE_JPEG){range[0]=0;range[1]=ten?65535.f/65472:1.f;range[3]=range[1];}
        auto key=std::make_pair(tex,slice);auto old=views.find(key);if(old!=views.end())return old->second;
        D3D11_SHADER_RESOURCE_VIEW_DESC d={};d.Format=ten?DXGI_FORMAT_R16_UNORM:DXGI_FORMAT_R8_UNORM;
        d.ViewDimension=D3D11_SRV_DIMENSION_TEXTURE2DARRAY;d.Texture2DArray.MipLevels=1;d.Texture2DArray.ArraySize=1;d.Texture2DArray.FirstArraySlice=slice;
        ID3D11ShaderResourceView *y=nullptr,*uv=nullptr;
        check(device->CreateShaderResourceView(tex,&d,&y),"luma view");
        d.Format=ten?DXGI_FORMAT_R16G16_UNORM:DXGI_FORMAT_R8G8_UNORM;
        HRESULT r=device->CreateShaderResourceView(tex,&d,&uv);if(FAILED(r)){y->Release();check(r,"chroma view");}
        if(views.size()>=192){y->Release();uv->Release();throw std::runtime_error("Surface view budget exceeded");}
        views[key]={y,uv};pools[tex]=(uint64_t)desc.Width*desc.Height*desc.ArraySize*3/(ten?1:2);return {y,uv};
    }
};
