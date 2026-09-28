import {test,expect} from '@playwright/test';
test('schema creates initial preset before dependent requests; editor survives workspace changes',async({page})=>{
 let initialized=false;
 await page.route('**/api/**',async route=>{const path=new URL(route.request().url()).pathname;let body:any=[];
 if(path==='/api/projects')body=[{id:'p',name:'测试项目'}];
 else if(path.endsWith('/schema')){await new Promise(r=>setTimeout(r,80));initialized=true;body={fields:[{key:'lr',kind:'number',default:0.01,has_default:true},{key:'enabled',kind:'boolean',default:true,has_default:true}]}}
 else if(path.endsWith('/presets')){expect(initialized).toBe(true);body=[{id:'preset',name:'源码默认值',parameters:{training:{lr:0.01,enabled:true},runtime:{gpu_count:1}}}]}
 else if(path.endsWith('/editor-initial')){expect(initialized).toBe(true);body={training:{lr:0.001,enabled:true},runtime:{gpu_count:2}}}
 else if(path.endsWith('/inspect'))body={branches:['main']};
 else if(path.endsWith('/parameter-display'))body={};
 else if(path==='/api/connection')body={connected:true};
 else if(path==='/api/queue')body={runs:[],paused:false};
 await route.fulfill({json:body});});
 await page.goto('/');await expect(page.getByLabel('lr',{exact:true})).toHaveValue('0.001');
 await page.getByLabel('lr',{exact:true}).fill('2K');await page.getByRole('button',{name:'运行监控',exact:true}).click();await page.getByRole('button',{name:'配置实验',exact:true}).click();await expect(page.getByLabel('lr',{exact:true})).toHaveValue('2K');
 await page.getByLabel('lr',{exact:true}).fill('invalid');await page.getByLabel('实验名称').fill('example');await expect(page.getByRole('button',{name:'启动实验',exact:true})).toBeDisabled();
 await page.screenshot({path:'test-results/workbench.png',fullPage:true});
});
test('empty workspaces stay usable without invented experimental results',async({page})=>{await page.route('**/api/**',route=>route.fulfill({json:route.request().url().endsWith('/connection')?{connected:false}:[]}));await page.goto('/');await expect(page.getByText('添加你的第一个项目')).toBeVisible();await page.getByRole('button',{name:'画图与列表',exact:true}).click();await expect(page.getByRole('button',{name:'下载 PNG'})).toBeDisabled();});
