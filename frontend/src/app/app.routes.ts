import { Routes } from '@angular/router';

import { authGuard, guestGuard, managerGuard } from './core/auth/guards';

export const routes: Routes = [
  {
    path: 'login',
    title: 'Sign in · LeaveDesk',
    canActivate: [guestGuard],
    loadComponent: () => import('./features/login/login-page').then((m) => m.LoginPage),
  },
  {
    path: '',
    canActivate: [authGuard],
    children: [
      {
        path: 'leave',
        title: 'My leave · LeaveDesk',
        loadComponent: () => import('./features/leave/my-leave-page').then((m) => m.MyLeavePage),
      },
      {
        path: 'approvals',
        title: 'Approvals · LeaveDesk',
        canActivate: [managerGuard],
        loadComponent: () =>
          import('./features/approvals/approvals-page').then((m) => m.ApprovalsPage),
      },
      { path: '', pathMatch: 'full', redirectTo: 'leave' },
    ],
  },
  { path: '**', redirectTo: 'leave' },
];
