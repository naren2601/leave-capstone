import { Routes } from '@angular/router';

export const routes: Routes = [
  {
    path: '',
    title: 'LeaveDesk',
    loadComponent: () => import('./features/status/status-page').then((m) => m.StatusPage),
  },
  { path: '**', redirectTo: '' },
];
