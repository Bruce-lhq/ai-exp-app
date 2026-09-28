import {afterEach,expect,test,vi} from 'vitest';
import {api} from '../src/app/api';
afterEach(()=>vi.unstubAllGlobals());
test('DELETE satisfies same-origin JSON security even without a supplied payload',async()=>{const request=vi.fn().mockResolvedValue({ok:true,status:200,json:async()=>({ok:true})});vi.stubGlobal('fetch',request);await api('/api/projects/a',undefined,'DELETE');expect(request.mock.calls[0][1]).toMatchObject({method:'DELETE',credentials:'same-origin',headers:{'Content-Type':'application/json'},body:'{}'})});
