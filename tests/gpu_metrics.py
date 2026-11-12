"""Windows PDH GPU engine counters, sampled for the test process tree."""
import ctypes as ct
import re


class DoubleValue(ct.Structure):
    _fields_ = [('status', ct.c_ulong), ('value', ct.c_double)]


class Item(ct.Structure):
    _fields_ = [('name', ct.c_wchar_p), ('formatted', DoubleValue)]


class GPU:
    def __init__(self):
        self.query = ct.c_void_p()
        self.counter = ct.c_void_p()
        self.error = None
        self.memory_counters={}
        self.memory_peak={}
        self.memory_errors={}
        self.peak = {}
        self.sums = {}
        self.count = 0
        self.pdh = ct.WinDLL('pdh')
        code = self.pdh.PdhOpenQueryW(None, 0, ct.byref(self.query))
        if not code:
            code = self.pdh.PdhAddEnglishCounterW(self.query, r'\GPU Engine(*)\Utilization Percentage', 0, ct.byref(self.counter))
        if not code:
            for name in ('Dedicated Usage','Shared Usage'):
                counter=ct.c_void_p()
                status=self.pdh.PdhAddEnglishCounterW(self.query,'\\GPU Process Memory(*)\\'+name,0,ct.byref(counter))
                if status:self.memory_errors[name]=f'{status & 0xffffffff:08x}'
                else:self.memory_counters[name]=counter
        if code:
            self.error = f'PDH status {code & 0xffffffff:08x}'
        else:
            self.pdh.PdhCollectQueryData(self.query)

    def sample(self, pids):
        if self.error:
            return
        code = self.pdh.PdhCollectQueryData(self.query)
        size, count = ct.c_ulong(), ct.c_ulong()
        code = self.pdh.PdhGetFormattedCounterArrayW(self.counter, 0x200, ct.byref(size), ct.byref(count), None)
        if not size.value:
            self.error = f'No GPU counter data ({code & 0xffffffff:08x})'
            return
        buffer = ct.create_string_buffer(size.value)
        code = self.pdh.PdhGetFormattedCounterArrayW(self.counter, 0x200, ct.byref(size), ct.byref(count), buffer)
        if code:
            return
        for kind,counter in self.memory_counters.items():
            memory_size,memory_count=ct.c_ulong(),ct.c_ulong()
            self.pdh.PdhGetFormattedCounterArrayW(counter,0x200,ct.byref(memory_size),ct.byref(memory_count),None)
            if not memory_size.value:continue
            memory_buffer=ct.create_string_buffer(memory_size.value)
            status=self.pdh.PdhGetFormattedCounterArrayW(counter,0x200,ct.byref(memory_size),ct.byref(memory_count),memory_buffer)
            if status:continue
            memory_items=ct.cast(memory_buffer,ct.POINTER(Item));total_bytes=0
            for i in range(memory_count.value):
                item=memory_items[i];match=re.search(r'pid_(\d+)',item.name or '')
                if match and int(match[1]) in pids and item.formatted.status in (0,1):total_bytes+=max(0,item.formatted.value)
            self.memory_peak[kind]=max(self.memory_peak.get(kind,0),total_bytes)
        items = ct.cast(buffer, ct.POINTER(Item))
        totals = {}
        for i in range(count.value):
            entry = items[i]
            match = re.search(r'pid_(\d+).*engtype_(.+)$', entry.name or '')
            if match and int(match[1]) in pids and entry.formatted.status in (0, 1):
                kind = match[2]
                totals[kind] = totals.get(kind, 0) + max(0, entry.formatted.value)
        self.count += 1
        for kind, value in totals.items():
            self.peak[kind] = max(self.peak.get(kind, 0), value)
            self.sums[kind] = self.sums.get(kind, 0) + value

    def finish(self):
        self.pdh.PdhCloseQuery(self.query)
        return {'peak_process_gpu_memory_MiB':{k:round(v/2**20,2) for k,v in self.memory_peak.items()},
                'memory_counter_errors':self.memory_errors,'samples': self.count, 'unavailable': self.error,
                'peak_engine_percent': {k: round(v, 2) for k, v in self.peak.items()},
                'mean_engine_percent': {k: round(v/self.count, 2) for k, v in self.sums.items()} if self.count else {}}
