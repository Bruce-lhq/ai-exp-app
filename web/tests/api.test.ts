import {afterEach,expect,test,vi} from 'vitest';
import {api} from '../src/app/api';
afterEach(()=>{vi.unstubAllGlobals();vi.useRealTimers();});
test('DELETE satisfies same-origin JSON security even without a supplied payload',async()=>{const request=vi.fn().mockResolvedValue({ok:true,status:200,json:async()=>({ok:true})});vi.stubGlobal('fetch',request);await api('/api/projects/a',undefined,'DELETE');expect(request.mock.calls[0][1]).toMatchObject({method:'DELETE',credentials:'same-origin',headers:{'Content-Type':'application/json'},body:'{}'})});
test('a restarted local service renews the session and retries the original request once', async () => {
 const request = vi.fn()
  .mockResolvedValueOnce(Response.json({detail:'请从应用首页打开工作台'}, {status:403}))
  .mockResolvedValueOnce(new Response('<html></html>'))
  .mockResolvedValueOnce(Response.json({series:[{id:'cached'}]}));
 vi.stubGlobal('fetch',request);
 expect(await api('/api/analysis/series',{history_ids:['cached']})).toEqual({series:[{id:'cached'}]});
 expect(request.mock.calls[1]).toEqual(['/', expect.objectContaining({credentials:'same-origin',cache:'no-store'})]);
 expect(request.mock.calls[0]).toEqual(request.mock.calls[2]);
});
test('simultaneous session failures share one renewal request', async () => {
 let renewed = false, renewals = 0;
 const request = vi.fn(async (path: string) => {
  if (path === '/') { renewals++; await new Promise(resolve => setTimeout(resolve, 20)); renewed=true; return new Response('<html></html>'); }
  return renewed ? Response.json({ok:true}) : Response.json({detail:'请从应用首页打开工作台'},{status:403});
 });
 vi.stubGlobal('fetch', request);
 await Promise.all([api('/api/history'),api('/api/templates'),api('/api/analysis/series',{history_ids:['cached']})]);
 expect(renewals).toBe(1);
});
test('other forbidden operations are never retried', async () => {
 const request = vi.fn().mockResolvedValue(Response.json({detail:'仅允许同源操作'},{status:403}));
 vi.stubGlobal('fetch',request);
 await expect(api('/api/analysis/series',{})).rejects.toThrow('仅允许同源操作');
 expect(request).toHaveBeenCalledTimes(1);
});

test('stalled reads time out and the next read can succeed', async () => {
 vi.useFakeTimers();
 const request = vi.fn((_path: string, options: RequestInit): Promise<any> => new Promise((_resolve, reject) => {
  options.signal!.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')));
 }));
 vi.stubGlobal('fetch',request);
 const result = expect(api('/api/projects')).rejects.toThrow('连接超时，数据尚未加载');
 await vi.advanceTimersByTimeAsync(20001);
 await result;
 request.mockImplementationOnce(async () => Response.json([{id:'restored'}]));
 expect(await api('/api/projects')).toEqual([{id:'restored'}]);
});
test('timeout includes a stalled response body', async () => {
 vi.useFakeTimers();
 vi.stubGlobal('fetch',vi.fn(async (_path: string, options: RequestInit) => ({
  ok:true,status:200,json:()=>new Promise((_resolve,reject)=>options.signal!.addEventListener('abort',()=>reject(new DOMException('Aborted','AbortError'))))
 })));
 const result=expect(api('/api/history')).rejects.toThrow('连接超时');
 await vi.advanceTimersByTimeAsync(20001);
 await result;
});
test('caller cancellation stays an AbortError rather than a timeout',async()=>{
 const caller=new AbortController();
 vi.stubGlobal('fetch',vi.fn((_path:string,options:RequestInit)=>new Promise((_resolve,reject)=>options.signal!.addEventListener('abort',()=>reject(new DOMException('Aborted','AbortError'))))));
 const result=api('/api/analysis/series',{},undefined,{signal:caller.signal});
 caller.abort();
 await expect(result).rejects.toMatchObject({name:'AbortError'});
});
