import {afterEach,expect,test,vi} from 'vitest';
import {api} from '../src/app/api';
afterEach(()=>vi.unstubAllGlobals());
test('DELETE satisfies same-origin JSON security even without a supplied payload',async()=>{const request=vi.fn().mockResolvedValue({ok:true,status:200,json:async()=>({ok:true})});vi.stubGlobal('fetch',request);await api('/api/projects/a',undefined,'DELETE');expect(request.mock.calls[0][1]).toMatchObject({method:'DELETE',credentials:'same-origin',headers:{'Content-Type':'application/json'},body:'{}'})});
test('a restarted local service renews the session and retries the original request once', async () => {
 const request = vi.fn()
  .mockResolvedValueOnce(Response.json({detail:'请从应用首页打开工作台'}, {status:403}))
  .mockResolvedValueOnce(new Response('<html></html>'))
  .mockResolvedValueOnce(Response.json({series:[{id:'cached'}]}));
 vi.stubGlobal('fetch',request);
 expect(await api('/api/analysis/series',{history_ids:['cached']})).toEqual({series:[{id:'cached'}]});
 expect(request.mock.calls[1]).toEqual(['/', {credentials:'same-origin',cache:'no-store'}]);
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
