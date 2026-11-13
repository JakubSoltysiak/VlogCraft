#pragma once
// Per-thread deadline wait; no global timer-resolution or power-plan change.
struct DeadlineWait {
 HANDLE timer=nullptr,event=nullptr;Distribution overshoot;
 DeadlineWait(HANDLE input):event(input){timer=CreateWaitableTimerExW(nullptr,nullptr,0x2,TIMER_ALL_ACCESS);}
 ~DeadlineWait(){if(timer)CloseHandle(timer);}
 void wait(int64_t microseconds){
  microseconds=std::clamp<int64_t>(microseconds,100,20000);auto began=Clock::now();
  if(timer){
   LARGE_INTEGER due;due.QuadPart=-microseconds*10;
   if(SetWaitableTimer(timer,&due,0,nullptr,nullptr,FALSE)){
    HANDLE handles[2]={event,timer};DWORD result=MsgWaitForMultipleObjectsEx(2,handles,25,QS_ALLINPUT,MWMO_INPUTAVAILABLE);
    if(result==WAIT_OBJECT_0+1)overshoot.add(std::max(0.,seconds(began)*1000-microseconds/1000.));return;
   }
  }
  MsgWaitForMultipleObjectsEx(1,&event,(DWORD)std::max<int64_t>(1,(microseconds+999)/1000),QS_ALLINPUT,MWMO_INPUTAVAILABLE);
 }
};
