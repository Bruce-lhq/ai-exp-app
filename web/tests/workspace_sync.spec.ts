import { test, expect } from '@playwright/test';

test('sync conflicts are explicit and background status never blocks the workspace', async ({page}) => {
  let conflicts = [{id:'conflict-1',kind:'presets',name:'参数组 A',local:{lr:1},remote:{lr:2}}];
  let choice = '';
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname;
    let body: any = [];
    if(path === '/api/settings/local') body={configured:true,local_settings:{}};
    if(path === '/api/connection') body={connected:true};
    if(path === '/api/queue') body={runs:[]};
    if(path === '/api/workspace-sync') body={mode:'client',state:conflicts.length?'conflict':'idle',conflicts,pending:1,revision:1};
    if(path === '/api/workspace-sync/conflicts/conflict-1') {choice=route.request().postDataJSON().choice;conflicts=[];body={};}
    await route.fulfill({json:body});
  });
  await page.goto('/');
  await expect(page.locator('.loading-overlay')).toHaveCount(0);
  await page.getByRole('button',{name:'跨设备同步',exact:true}).click();
  await expect(page.getByRole('heading',{name:'参数组 A'})).toBeVisible();
  await page.getByRole('button',{name:'保留本机'}).click();
  await expect.poll(()=>choice).toBe('local');
  await expect(page.getByRole('heading',{name:'参数组 A'})).toHaveCount(0);
});

test('chart settings migrate to backend and survive reload without overwriting unsaved edits', async ({page}) => {
  let saved:any={};
  await page.addInitScript(()=>{if(!localStorage.getItem('analysis.settings'))localStorage.setItem('analysis.settings', JSON.stringify({title:'本机图标题'}));});
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname;
    let body:any=[];
    if(path === '/api/settings/local') body={configured:true,local_settings:{}};
    if(path === '/api/connection') body={connected:true};
    if(path === '/api/queue') body={runs:[]};
    if(path === '/api/workspace-sync') body={mode:'off',state:'idle',conflicts:[]};
    if(path === '/api/workspace-sync/view') {
      if(route.request().method()==='PUT') saved=route.request().postDataJSON();
      body=saved;
    }
    if(path === '/api/analysis/series') body={series:[],metrics:['val_ppl']};
    await route.fulfill({json:body});
  });
  await page.goto('/');
  await page.getByRole('button',{name:'画图与列表',exact:true}).click();
  await expect.poll(()=>saved.settings?.title).toBe('本机图标题');
  const title=page.getByLabel('图标题',{exact:true});
  await title.fill('跨设备标题');
  await expect.poll(()=>saved.settings?.title).toBe('跨设备标题');
  await page.reload();
  await page.getByRole('button',{name:'画图与列表',exact:true}).click();
  await expect(title).toHaveValue('跨设备标题');
});

test('offline chart edits remain pending across reload and upload after reconnect', async ({page}) => {
  let online=true;
  let saved:any={};
  await page.route('**/api/**', async route => {
    const path=new URL(route.request().url()).pathname;
    let body:any=[];
    if(path==='/api/settings/local') body={configured:true,local_settings:{}};
    if(path==='/api/connection') body={connected:true};
    if(path==='/api/queue') body={runs:[]};
    if(path==='/api/workspace-sync') body={mode:'off',state:'idle',conflicts:[]};
    if(path==='/api/analysis/series') body={series:[],metrics:['val_ppl']};
    if(path==='/api/workspace-sync/view') {
      if(!online) return route.abort();
      if(route.request().method()==='PUT') saved=route.request().postDataJSON();
      body=saved;
    }
    await route.fulfill({json:body});
  });
  await page.goto('/');
  await page.getByRole('button',{name:'画图与列表',exact:true}).click();
  await expect.poll(()=>saved.settings?.title).toBe('验证集困惑度');
  online=false;
  await page.getByLabel('图标题',{exact:true}).fill('离线保留标题');
  await expect(page.getByText('图表设置尚未保存到后台',{exact:false})).toBeVisible();
  online=true;
  await page.reload();
  await page.getByRole('button',{name:'画图与列表',exact:true}).click();
  await expect(page.getByLabel('图标题',{exact:true})).toHaveValue('离线保留标题');
  await expect.poll(()=>saved.settings?.title).toBe('离线保留标题');
});
