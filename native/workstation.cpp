// Local technical inventory only. No serials, device paths, usernames or network IDs.
#include "media.h"
#include <dxgi1_6.h>
#include <set>
#include <dwmapi.h>
std::string utf8(const wchar_t* value){
 int n=WideCharToMultiByte(CP_UTF8,0,value,-1,nullptr,0,nullptr,nullptr);
 std::string s(n,'\0');WideCharToMultiByte(CP_UTF8,0,value,-1,s.data(),n,nullptr,nullptr);s.pop_back();return s;
}
int main(){
 try{
 SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2);
 Com<IDXGIFactory1> factory;check(CreateDXGIFactory1(__uuidof(IDXGIFactory1),(void**)factory.out()),"factory");
 std::cout<<"{\"adapters\":[";bool comma=false;
 for(UINT i=0;;i++){
  Com<IDXGIAdapter1> adapter;if(factory->EnumAdapters1(i,adapter.out())==DXGI_ERROR_NOT_FOUND)break;
  DXGI_ADAPTER_DESC1 info={};adapter->GetDesc1(&info);if(info.Flags&DXGI_ADAPTER_FLAG_SOFTWARE)continue;
  if(comma)std::cout<<",";comma=true;Com<ID3D11Device> device;Com<ID3D11DeviceContext> context;D3D_FEATURE_LEVEL level;
  check(D3D11CreateDevice(adapter,D3D_DRIVER_TYPE_UNKNOWN,nullptr,0,(D3D_FEATURE_LEVEL[]){D3D_FEATURE_LEVEL_11_1,D3D_FEATURE_LEVEL_11_0},2,D3D11_SDK_VERSION,device.out(),&level,context.out()),"D3D11");
  D3D11_FEATURE_DATA_D3D11_OPTIONS2 options={};bool uma=SUCCEEDED(device->CheckFeatureSupport(D3D11_FEATURE_D3D11_OPTIONS2,&options,sizeof(options)))&&options.UnifiedMemoryArchitecture;
  std::cout<<"{\"name\":\""<<utf8(info.Description)<<"\",\"feature_level\":"<<level<<",\"unified_memory\":"<<(uma?"true":"false")
   <<",\"dedicated_video_MiB\":"<<info.DedicatedVideoMemory/(1024*1024)<<",\"shared_system_MiB\":"<<info.SharedSystemMemory/(1024*1024);
  Com<IDXGIAdapter3> budget;if(SUCCEEDED(adapter->QueryInterface(__uuidof(IDXGIAdapter3),(void**)budget.out()))){
   DXGI_QUERY_VIDEO_MEMORY_INFO memory={};budget->QueryVideoMemoryInfo(0,DXGI_MEMORY_SEGMENT_GROUP_LOCAL,&memory);
   std::cout<<",\"local_budget_MiB\":"<<memory.Budget/(1024*1024)<<",\"local_current_MiB\":"<<memory.CurrentUsage/(1024*1024);
   budget->QueryVideoMemoryInfo(0,DXGI_MEMORY_SEGMENT_GROUP_NON_LOCAL,&memory);
   std::cout<<",\"nonlocal_budget_MiB\":"<<memory.Budget/(1024*1024);
  }
  Com<ID3D11VideoDevice> video;check(device->QueryInterface(__uuidof(ID3D11VideoDevice),(void**)video.out()),"video device");
  std::cout<<",\"decoder_profile_count\":"<<video->GetVideoDecoderProfileCount()<<",\"decode_formats\":[";bool dc=false;
  for(UINT p=0;p<video->GetVideoDecoderProfileCount();p++){
   GUID profile;video->GetVideoDecoderProfile(p,&profile);const char* name=nullptr;
   if(IsEqualGUID(profile,D3D11_DECODER_PROFILE_H264_VLD_NOFGT))name="h264";else if(IsEqualGUID(profile,D3D11_DECODER_PROFILE_HEVC_VLD_MAIN))name="hevc-main";else if(IsEqualGUID(profile,D3D11_DECODER_PROFILE_HEVC_VLD_MAIN10))name="hevc-main10";
   if(!name)continue;BOOL nv12=FALSE,p010=FALSE;video->CheckVideoDecoderFormat(&profile,DXGI_FORMAT_NV12,&nv12);video->CheckVideoDecoderFormat(&profile,DXGI_FORMAT_P010,&p010);
   if(dc)std::cout<<",";dc=true;std::cout<<"{\"codec\":\""<<name<<"\",\"NV12\":"<<(nv12?"true":"false")<<",\"P010\":"<<(p010?"true":"false")<<"}";
  }
  std::cout<<"],\"outputs\":[";bool oc=false;
  for(UINT o=0;;o++){
   Com<IDXGIOutput> output;if(adapter->EnumOutputs(o,output.out())==DXGI_ERROR_NOT_FOUND)break;
   DXGI_OUTPUT_DESC desc={};output->GetDesc(&desc);if(!desc.AttachedToDesktop)continue;
   if(oc)std::cout<<",";oc=true;std::cout<<"{\"width\":"<<desc.DesktopCoordinates.right-desc.DesktopCoordinates.left<<",\"height\":"<<desc.DesktopCoordinates.bottom-desc.DesktopCoordinates.top;
   Com<IDXGIOutput6> advanced;if(SUCCEEDED(output->QueryInterface(__uuidof(IDXGIOutput6),(void**)advanced.out()))){
    DXGI_OUTPUT_DESC1 color={};advanced->GetDesc1(&color);std::cout<<",\"bits_per_color\":"<<color.BitsPerColor<<",\"color_space\":"<<color.ColorSpace<<",\"max_luminance_nits\":"<<color.MaxLuminance;
   }
   UINT count=0;output->GetDisplayModeList(DXGI_FORMAT_B8G8R8A8_UNORM,0,&count,nullptr);std::vector<DXGI_MODE_DESC> modes(count);output->GetDisplayModeList(DXGI_FORMAT_B8G8R8A8_UNORM,0,&count,modes.data());
   std::set<std::pair<UINT,UINT>> rates;for(auto& m:modes)if(m.Width==(UINT)(desc.DesktopCoordinates.right-desc.DesktopCoordinates.left)&&m.Height==(UINT)(desc.DesktopCoordinates.bottom-desc.DesktopCoordinates.top))rates.insert({m.RefreshRate.Numerator,m.RefreshRate.Denominator});
   std::cout<<",\"available_refresh_rates\":[";bool rc=false;for(auto rate:rates){if(rc)std::cout<<",";rc=true;std::cout<<"["<<rate.first<<","<<rate.second<<"]";}std::cout<<"]}";
  }std::cout<<"]}";
 }
 DWORD bytes=0;GetLogicalProcessorInformationEx(RelationProcessorCore,nullptr,&bytes);std::vector<char> data(bytes);
 GetLogicalProcessorInformationEx(RelationProcessorCore,(PSYSTEM_LOGICAL_PROCESSOR_INFORMATION_EX)data.data(),&bytes);
 std::cout<<"],\"cpu_cores\":[";bool cc=false;
 for(DWORD offset=0;offset<bytes;){
  auto* p=(PSYSTEM_LOGICAL_PROCESSOR_INFORMATION_EX)(data.data()+offset);if(cc)std::cout<<",";cc=true;int logical=0;
  for(WORD g=0;g<p->Processor.GroupCount;g++){auto mask=p->Processor.GroupMask[g].Mask;while(mask){logical+=mask&1;mask>>=1;}}
  std::cout<<"{\"efficiency_class\":"<<(int)p->Processor.EfficiencyClass<<",\"logical_threads\":"<<logical<<"}";offset+=p->Size;
 }
 SYSTEM_POWER_STATUS power={};GetSystemPowerStatus(&power);
 DEVMODEW dm={};dm.dmSize=sizeof(dm);EnumDisplaySettingsW(nullptr,ENUM_CURRENT_SETTINGS,&dm);
 DWM_TIMING_INFO timing={};timing.cbSize=sizeof(timing);DwmGetCompositionTimingInfo(nullptr,&timing);
 std::cout<<"],\"dwm_refresh_rate\":["<<timing.rateRefresh.uiNumerator<<","<<timing.rateRefresh.uiDenominator<<"],\"active_refresh_hz\":"<<dm.dmDisplayFrequency<<",\"ac_line_status\":"<<(int)power.ACLineStatus<<",\"battery_percent\":"<<(int)power.BatteryLifePercent<<"}"<<std::endl;
 return 0;
 }catch(...){std::cout<<"{\"unavailable\":true}"<<std::endl;return 1;}
}
