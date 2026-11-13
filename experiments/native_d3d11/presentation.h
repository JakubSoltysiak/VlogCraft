// Optional SDR presentation proof, independent of WebView2's encoded-media path.
#include <thread>
LRESULT CALLBACK window_proc(HWND hwnd,UINT msg,WPARAM w,LPARAM l){
    if(msg==WM_DESTROY){PostQuitMessage(0);return 0;}return DefWindowProcW(hwnd,msg,w,l);
}
struct Display {
    HWND window=nullptr;Com<IDXGISwapChain> swap;Com<ID3D11RenderTargetView> target;
    Com<ID3D11ShaderResourceView> image;Com<ID3D11PixelShader> shader;
    unsigned calls=0;bool statistics=false;unsigned displayed=0,firstDisplayed=0;
    Clock::time_point firstReturn,lastReturn;double presentWait=0;LONGLONG firstSync=0,lastSync=0;
    Display(ID3D11Device* device,ID3D11Texture2D* texture,int width,int height,HWND parent,decltype(&D3DCompile) compile){
        WNDCLASSW wc={};wc.lpfnWndProc=window_proc;wc.hInstance=GetModuleHandleW(nullptr);wc.lpszClassName=L"VlogCraftEnginePrototype";
        RegisterClassW(&wc);
        DWORD style=parent?(WS_CHILD|WS_VISIBLE):WS_OVERLAPPEDWINDOW;
        RECT bounds={0,0,width,height};if(!parent)AdjustWindowRect(&bounds,style,FALSE);
        window=CreateWindowW(wc.lpszClassName,L"VlogCraft GPU prototype",style,CW_USEDEFAULT,CW_USEDEFAULT,
                             bounds.right-bounds.left,bounds.bottom-bounds.top,parent,nullptr,wc.hInstance,nullptr);
        if(!window)throw std::runtime_error("Cannot create native presentation window");
        if(parent)SetWindowPos(window,HWND_TOP,0,0,width,height,SWP_NOACTIVATE);
        ShowWindow(window,SW_SHOWNOACTIVATE);
        Com<IDXGIDevice> dxgi;Com<IDXGIAdapter> adapter;Com<IDXGIFactory> factory;
        check(device->QueryInterface(__uuidof(IDXGIDevice),(void**)dxgi.out()),"DXGI device");check(dxgi->GetAdapter(adapter.out()),"adapter");
        check(adapter->GetParent(__uuidof(IDXGIFactory),(void**)factory.out()),"factory");
        DXGI_SWAP_CHAIN_DESC desc={};desc.BufferDesc.Width=width;desc.BufferDesc.Height=height;desc.BufferDesc.Format=DXGI_FORMAT_B8G8R8A8_UNORM;
        desc.SampleDesc.Count=1;desc.BufferUsage=DXGI_USAGE_RENDER_TARGET_OUTPUT;desc.BufferCount=2;desc.OutputWindow=window;desc.Windowed=TRUE;desc.SwapEffect=DXGI_SWAP_EFFECT_FLIP_SEQUENTIAL;
        check(factory->CreateSwapChain(device,&desc,swap.out()),"swap chain");
        Com<ID3D11Texture2D> back;check(swap->GetBuffer(0,__uuidof(ID3D11Texture2D),(void**)back.out()),"back buffer");
        check(device->CreateRenderTargetView(back,nullptr,target.out()),"display target");check(device->CreateShaderResourceView(texture,nullptr,image.out()),"display image");
        const char* code="Texture2D<float4> image:register(t0);SamplerState s:register(s0);float4 display(float4 p:SV_Position,float2 uv:TEXCOORD0):SV_Target{return image.Sample(s,uv);}";
        Com<ID3DBlob> blob,error;check(compile(code,strlen(code),"display",nullptr,nullptr,"display","ps_5_0",D3DCOMPILE_OPTIMIZATION_LEVEL3,0,blob.out(),error.out()),"display shader compile");
        check(device->CreatePixelShader(blob->GetBufferPointer(),blob->GetBufferSize(),nullptr,shader.out()),"display shader");
    }
    void present(ID3D11DeviceContext* context){
        MSG message;while(PeekMessageW(&message,nullptr,0,0,PM_REMOVE)){if(message.message==WM_QUIT)throw std::runtime_error("Presentation cancelled");TranslateMessage(&message);DispatchMessageW(&message);}
        ID3D11RenderTargetView* rt=target;context->OMSetRenderTargets(1,&rt,nullptr);context->OMSetBlendState(nullptr,nullptr,0xffffffff);
        context->PSSetShader(shader,nullptr,0);ID3D11ShaderResourceView* srv=image;context->PSSetShaderResources(0,1,&srv);context->Draw(3,0);
        ID3D11ShaderResourceView* empty=nullptr;context->PSSetShaderResources(0,1,&empty);
        auto began=Clock::now();check(swap->Present(1,0),"Present");presentWait+=seconds(began);calls++;
        lastReturn=Clock::now();if(calls==1)firstReturn=lastReturn;
        DXGI_FRAME_STATISTICS stat={};if(SUCCEEDED(swap->GetFrameStatistics(&stat))){statistics=true;displayed=stat.PresentCount;
            if(!firstSync&&stat.PresentCount){firstSync=stat.SyncQPCTime.QuadPart;firstDisplayed=stat.PresentCount;}lastSync=stat.SyncQPCTime.QuadPart;}
    }
    double callRate()const{return calls>1?(calls-1)/std::chrono::duration<double>(lastReturn-firstReturn).count():0;}
    double displayRate()const{LARGE_INTEGER frequency;QueryPerformanceFrequency(&frequency);return firstSync&&lastSync>firstSync?(displayed-firstDisplayed)*(double)frequency.QuadPart/(lastSync-firstSync):0;}
    ~Display(){if(window)DestroyWindow(window);}
};
