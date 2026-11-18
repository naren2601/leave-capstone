import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { provideRouter, Router } from '@angular/router';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';

import { fakeToken } from '../../../testing/tokens';
import { authInterceptor, unauthorizedInterceptor } from '../../core/auth/auth.interceptor';
import { LoginPage } from './login-page';

async function setup(inputs: Record<string, string> = {}) {
  sessionStorage.clear();
  const user = userEvent.setup();
  await render(LoginPage, {
    inputs,
    providers: [
      provideHttpClient(withInterceptors([authInterceptor, unauthorizedInterceptor])),
      provideHttpClientTesting(),
      provideRouter([]),
    ],
  });
  const navigate = vi.spyOn(TestBed.inject(Router), 'navigateByUrl').mockResolvedValue(true);
  return { user, navigate, http: TestBed.inject(HttpTestingController) };
}

const signIn = () => screen.getByRole('button', { name: /sign in/i });

describe('LoginPage', () => {
  it('UI-3: Sign in stays disabled until a real email and a password are typed', async () => {
    const { user } = await setup();
    expect(signIn()).toBeDisabled();

    await user.type(screen.getByLabelText('Email'), 'not-an-email');
    await user.type(screen.getByLabelText('Password'), 'demo1234');
    expect(signIn()).toBeDisabled();

    await user.clear(screen.getByLabelText('Email'));
    await user.type(screen.getByLabelText('Email'), 'asha@leavedesk.dev');
    expect(signIn()).toBeEnabled();
  });

  it('UI-3: shows a message under a badly typed email', async () => {
    const { user } = await setup();

    await user.type(screen.getByLabelText('Email'), 'asha');
    await user.tab();

    expect(await screen.findByText(/enter an email like/i)).toBeVisible();
  });

  it('UI-1: a correct login goes to My leave', async () => {
    const { user, http, navigate } = await setup();

    await user.type(screen.getByLabelText('Email'), 'asha@leavedesk.dev');
    await user.type(screen.getByLabelText('Password'), 'demo1234');
    await user.click(signIn());
    http.expectOne('/api/auth/login').flush({ access_token: fakeToken('employee') });

    await vi.waitFor(() => expect(navigate).toHaveBeenCalledWith('/leave'));
  });

  it('goes back to the page the user wanted, but only inside this app', async () => {
    const { user, http, navigate } = await setup({ returnUrl: '//evil.example.com' });

    await user.type(screen.getByLabelText('Email'), 'ravi@leavedesk.dev');
    await user.type(screen.getByLabelText('Password'), 'demo1234');
    await user.click(signIn());
    http.expectOne('/api/auth/login').flush({ access_token: fakeToken('manager') });

    await vi.waitFor(() => expect(navigate).toHaveBeenCalledWith('/leave'));
  });

  it('UI-2: a wrong password shows one message and stays on the page', async () => {
    const { user, http, navigate } = await setup();

    await user.type(screen.getByLabelText('Email'), 'asha@leavedesk.dev');
    await user.type(screen.getByLabelText('Password'), 'wrong-password');
    await user.click(signIn());
    http
      .expectOne('/api/auth/login')
      .flush({ error: { code: 'UNAUTHORIZED' } }, { status: 401, statusText: 'Unauthorized' });

    expect(await screen.findByRole('alert')).toHaveTextContent('Email or password is wrong.');
    expect(navigate).not.toHaveBeenCalled();
    expect(screen.getByLabelText('Password')).toHaveValue('');
  });

  it('after an expired session it asks the user to sign in again', async () => {
    await setup({ reason: 'expired' });

    expect(screen.getByRole('status')).toHaveTextContent('Please sign in again.');
  });
});
