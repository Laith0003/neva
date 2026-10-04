#!/usr/bin/env node
/**
 * ck - Context Keeper v2
 * resume.mjs - full project briefing
 *
 * Usage: node resume.mjs [name|number]
 * stdout: bordered briefing box
 * exit 0: success  exit 1: not found
 */

import { existsSync } from 'fs';
import { resolveContext, renderBriefingBox, gitBranch } from './shared.mjs';

const arg = process.argv[2];
const cwd = process.env.PWD || process.cwd();

const resolved = resolveContext(arg, cwd);
if (!resolved) {
  const hint = arg ? `No project matching "${arg}".` : 'This directory is not registered.';
  console.log(`${hint} Run /ck:init to register it.`);
  process.exit(1);
}

const { context, projectPath } = resolved;

// Attempt to cd to the project path
if (projectPath && projectPath !== cwd) {
  if (existsSync(projectPath)) {
    console.log(`→ cd ${projectPath}`);
  } else {
    console.log(`WARNING Path not found: ${projectPath}`);
  }
}

console.log('');
console.log(renderBriefingBox(context));

// Cross-branch resume is allowed; say so when the branch differs (from gstack context-restore).
const savedBranch = context.sessions?.[context.sessions.length - 1]?.branch;
const currentBranch = gitBranch(projectPath && existsSync(projectPath) ? projectPath : cwd);
if (savedBranch && currentBranch && savedBranch !== currentBranch) {
  console.log('');
  console.log(`NOTE This context was saved on branch ${savedBranch}. You are on ${currentBranch}. Switch branches before continuing if the work lives there.`);
}
