import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { readFileSync } from 'node:fs';
const source = readFileSync(new URL('../src/ai_exp_app/__init__.py', import.meta.url), 'utf8');
const version = source.match(/^__version__ = "([^"]+)"$/m)?.[1];
if (!version) throw new Error('Application version is missing');
export default defineConfig({define:{__APP_VERSION__:JSON.stringify(version)},plugins:[react()],server:{proxy:{'/api':'http://127.0.0.1:8765'}},test:{environment:'node'}} as any);
