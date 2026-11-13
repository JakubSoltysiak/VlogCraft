// Bounded generated scratch file; direct I/O, one 128 MiB write, deleted on close.
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <chrono>
#include <vector>
#include <algorithm>
#include <iostream>
#include <stdexcept>
#include <string>
using Clock=std::chrono::steady_clock;
double elapsed(Clock::time_point start){return std::chrono::duration<double>(Clock::now()-start).count();}
int wmain(int argc,wchar_t** argv){
 if(argc!=2)return 2;
 HANDLE file=CreateFileW(argv[1],GENERIC_READ|GENERIC_WRITE,0,nullptr,CREATE_NEW,
  FILE_ATTRIBUTE_TEMPORARY|FILE_FLAG_DELETE_ON_CLOSE|FILE_FLAG_NO_BUFFERING|FILE_FLAG_WRITE_THROUGH,nullptr);
 if(file==INVALID_HANDLE_VALUE){std::cout<<"{\"available\":false}"<<std::endl;return 1;}
 const DWORD chunk=8*1024*1024,blocks=16;void* buffer=VirtualAlloc(nullptr,chunk,MEM_COMMIT|MEM_RESERVE,PAGE_READWRITE);int code=0;
 try{
  if(!buffer)throw std::runtime_error("memory");memset(buffer,0x65,chunk);DWORD done=0;
  auto began=Clock::now();
  for(DWORD i=0;i<blocks;i++)if(!WriteFile(file,buffer,chunk,&done,nullptr)||done!=chunk)throw std::runtime_error("write");
  double write=elapsed(began);LARGE_INTEGER pos={};SetFilePointerEx(file,pos,nullptr,FILE_BEGIN);began=Clock::now();
  for(DWORD i=0;i<blocks;i++)if(!ReadFile(file,buffer,chunk,&done,nullptr)||done!=chunk)throw std::runtime_error("read");
  double read=elapsed(began);std::vector<double> latency;uint32_t rng=1729;
  for(int i=0;i<512;i++){
   rng=rng*1664525+1013904223;pos.QuadPart=(rng%((chunk*blocks)/4096))*4096LL;
   auto start=Clock::now();if(!SetFilePointerEx(file,pos,nullptr,FILE_BEGIN)||!ReadFile(file,buffer,4096,&done,nullptr)||done!=4096)throw std::runtime_error("random read");
   latency.push_back(elapsed(start)*1000);
  }std::sort(latency.begin(),latency.end());
  std::cout<<"{\"available\":true,\"bytes_written\":"<<chunk*blocks<<",\"direct_io\":true,\"sequential_write_MiB_s\":"<<128/write
   <<",\"sequential_read_MiB_s\":"<<128/read<<",\"random_4k_read_p50_ms\":"<<latency[256]<<",\"random_4k_read_p95_ms\":"<<latency[486]
   <<",\"random_read_count\":512}"<<std::endl;
 }catch(...){std::cout<<"{\"available\":false}"<<std::endl;code=1;}
 if(buffer)VirtualFree(buffer,0,MEM_RELEASE);CloseHandle(file);return code;
}
