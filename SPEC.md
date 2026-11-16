# LeaveDesk: Specification

LeaveDesk lets employees apply for leave and lets managers approve or reject it.
This first version is plain Python: no web framework and no database.

## 1. Scope

**In scope:** applying for, approving, rejecting and cancelling leave; balances;
working-day calculation; overlap detection; notifications; audit logging.

**Out of scope for this version:** public holidays, carry-over between leave years,
part-time schedules, a real email server, a real database, and login.

## 2. Entities

| Entity | Fields | Notes |
|---|---|---|
| **Employee** | `id`, `name`, `email`, `manager_id` | `manager_id` cannot be the employee's own id. |
| **Manager** | Everything on Employee | A Manager *is an* Employee, so it inherits. Can approve only direct reports. |
| **LeaveType** | `ANNUAL`, `SICK`, `CASUAL` | Each type has its own policy. |
| **LeaveRequest** | `id`, `employee_id`, `leave_type`, `start_date`, `end_date`, `day_part`, `reason`, `status`, `days`, `decision_note` | `status` is `PENDING`, `APPROVED`, `REJECTED` or `CANCELLED`. `day_part` is `FULL`, `AM` or `PM`. |
| **LeaveBalance** | `employee_id`, `leave_type`, `entitled`, `used`, `pending` | `available = entitled - used - pending`. |
| **Notification** | `id`, `recipient`, `event`, `message`, `read`, `created_at` | `read` starts as `False`. `id` and `created_at` were added on Day 2 for the API. |

### Leave policies

| Type | Days per year | Rule |
|---|---|---|
| Annual | 18 | Must start at least 3 calendar days from today. |
| Sick | 10 | May be backdated by up to 7 calendar days. |
| Casual | 6 | Cannot start in the past. At most 2 working days per request. |

### Request status changes

```
PENDING  -> APPROVED | REJECTED | CANCELLED
APPROVED -> CANCELLED   (only before the leave starts)
REJECTED -> nothing     (final)
CANCELLED -> nothing    (final)
```

### Who is notified

| Event | Employee | Manager |
|---|---|---|
| Submitted | Yes (confirmation) | Yes (action needed) |
| Approved | Yes | No |
| Rejected | Yes | No |
| Cancelled | Yes (confirmation) | Yes |

Every recipient receives the notification on every configured channel (email and in-app).
Delivery is concurrent. A failed delivery is logged and does not undo the leave action.

## 3. Functional requirements

### FR-1: Apply for leave

- **AC-1.1** Given an employee with a manager and enough balance,
  when they apply with valid dates and a valid reason,
  then a request is saved as `PENDING` with its working days calculated.
- **AC-1.2** Given a reason shorter than 5 characters after trimming, or longer than 500,
  when the employee applies,
  then `InvalidLeaveRequestError` is raised and nothing is saved.
- **AC-1.3** Given an annual request starting in fewer than 3 days,
  when the employee applies,
  then `PolicyViolationError` is raised.
- **AC-1.4** Given an employee with no manager,
  when they apply,
  then `InvalidLeaveRequestError` is raised because nobody can approve it.

### FR-2: Count working days

- **AC-2.1** Given a range from Friday to Tuesday,
  when working days are counted,
  then the result is 3, because Saturday and Sunday are skipped.
- **AC-2.2** Given a range containing only a Saturday and Sunday,
  when the employee applies,
  then `InvalidLeaveRequestError` is raised.
- **AC-2.3** Given a half-day request on a weekday,
  when days are counted,
  then the result is 0.5.

### FR-3: Stop overlapping requests

- **AC-3.1** Given an employee with a `PENDING` or `APPROVED` request,
  when they apply for dates that overlap it,
  then `OverlappingLeaveError` is raised.
- **AC-3.2** Given an employee with a `REJECTED` or `CANCELLED` request,
  when they apply for the same dates,
  then the new request is accepted.
- **AC-3.3** Given an `AM` half-day on a date,
  when the employee applies for a `PM` half-day on that date,
  then the new request is accepted.

### FR-4: Manage balances

- **AC-4.1** Given 18 days available,
  when the employee applies for 3 days,
  then `pending` becomes 3 and `available` becomes 15.
- **AC-4.2** Given fewer days available than requested,
  when the employee applies,
  then `InsufficientBalanceError` is raised and the balance does not change.
- **AC-4.3** Given several pending requests,
  when a new request would exceed what is left after them,
  then `InsufficientBalanceError` is raised, because pending days are already reserved.

### FR-5: Approve a request

- **AC-5.1** Given a `PENDING` request,
  when the employee's manager approves it,
  then its status is `APPROVED` and its days move from `pending` to `used`.
- **AC-5.2** Given a user who is not the employee's manager,
  when they try to approve,
  then `NotAuthorizedError` is raised and nothing changes.
- **AC-5.3** Given a request that is not `PENDING`,
  when the manager approves it,
  then `InvalidTransitionError` is raised.

### FR-6: Reject a request

- **AC-6.1** Given a `PENDING` request,
  when the manager rejects it with a comment,
  then its status is `REJECTED`, the comment is stored, and the pending days return to `available`.
- **AC-6.2** Given an empty comment,
  when the manager rejects,
  then `InvalidLeaveRequestError` is raised and the status stays `PENDING`.
- **AC-6.3** Given a request that is not `PENDING`,
  when the manager rejects it,
  then `InvalidTransitionError` is raised.

### FR-7: Cancel a request

- **AC-7.1** Given a `PENDING` request,
  when its owner cancels it,
  then its status is `CANCELLED` and the pending days return to `available`.
- **AC-7.2** Given an `APPROVED` request that has not started,
  when its owner cancels it,
  then its status is `CANCELLED` and the used days return to `available`.
- **AC-7.3** Given an `APPROVED` request that has started,
  when its owner cancels it,
  then `InvalidTransitionError` is raised.
- **AC-7.4** Given a user who does not own the request,
  when they try to cancel it,
  then `NotAuthorizedError` is raised.

### FR-8: Notify people

- **AC-8.1** Given a submit, approve, reject or cancel action that succeeds,
  when it completes,
  then a notification is sent to each recipient in the table in section 2.
- **AC-8.2** Given several recipients and channels,
  when notifications are sent,
  then they run concurrently with `asyncio.gather`.
- **AC-8.3** Given one channel that fails,
  when notifications are sent,
  then the other deliveries still finish and the leave action stays saved.
- **AC-8.4** Given an in-app notification,
  when the recipient marks it read,
  then its `read` flag is `True` and the unread count falls by one.

### FR-9: Audit and timing

- **AC-9.1** Given any `LeaveService` call,
  when it succeeds or fails,
  then the call, its outcome and its duration are logged.
- **AC-9.2** Given an operation wrapped in the timing context manager,
  when it finishes, even with an error,
  then its elapsed time is recorded and logged.

## 4. Edge cases and validation rules

| # | Edge case | Behaviour | Result |
|---|---|---|---|
| **EC-1** | End date before start date | Rejected | `InvalidLeaveRequestError` |
| **EC-2** | Weekends inside a range | Weekend days are not charged. A range with only weekend days is rejected. | Correct day count, or `InvalidLeaveRequestError` |
| **EC-3** | Overlapping requests | Rejected if the other request is `PENDING` or `APPROVED`. Opposite half-days on one date do not clash. | `OverlappingLeaveError` |
| **EC-4** | Insufficient balance | Rejected. Pending days count as reserved. | `InsufficientBalanceError` |
| **EC-5** | Half-day leave | Costs 0.5 days. Must be one weekday, so a multi-day or weekend half-day is rejected. | 0.5 days, or `InvalidLeaveRequestError` |

Other validation rules:

- Reason: 5 to 500 characters after trimming spaces.
- Status: must be one of the four defined values.
- Name: cannot be blank.
- Email: must look like `name@domain.tld`.
- Unknown employee or request ids raise `NotFoundError`.

## 5. Task breakdown

All paths are under `backend/leavedesk/`. All tests are in `backend/tests/`.

| Requirement | Code | Tests | Branch |
|---|---|---|---|
| FR-1 Apply | `domain/models.py`, `domain/policies.py`, `LeaveService.apply` in `domain/service.py` | `test_models.py`, `test_policies.py`, `test_service.py` | `feature/domain-models`, `feature/policies`, `feature/leave-service` |
| FR-2 Working days | `domain/dates.py` (`working_days`, `count_leave_days`) | `test_dates.py` | `feature/working-days` |
| FR-3 Overlaps | `domain/dates.py` (`requests_overlap`, `find_overlap`) | `test_dates.py`, `test_service.py` | `feature/working-days` |
| FR-4 Balances | `domain/policies.py` (`LeaveBalance`) | `test_policies.py`, `test_service.py` | `feature/policies` |
| FR-5 Approve | `LeaveService.approve`, `LeaveRequest.transition_to` | `test_models.py`, `test_service.py` | `feature/domain-models`, `feature/leave-service` |
| FR-6 Reject | `LeaveService.reject` | `test_service.py` | `feature/leave-service` |
| FR-7 Cancel | `LeaveService.cancel` | `test_service.py` | `feature/leave-service` |
| FR-8 Notifications | `domain/notifications.py` | `test_notifications.py`, `test_service.py` | `feature/leave-service` |
| FR-9 Audit and timing | `domain/instrumentation.py` (`@audit`, `timed`) | `test_instrumentation.py` | `feature/leave-service` |
| Errors | `domain/exceptions.py` | Covered by all tests | `feature/domain-models` |
| Storage | `domain/repository.py` | `test_service.py` | `feature/leave-service` |
| End-to-end demo | `demo.py` | `test_demo.py` | `feature/demo` |
| REST API (Day 2) | `api/` (see `API_SPEC.md`) | `tests/api/` | `feature/api` |

The demo (`python -m leavedesk.demo`) runs the happy path and EC-1 to EC-5,
and prints PASS for each edge case that raises the expected exception.

## 6. Design decisions

- **Inheritance** is used where one thing is a kind of another: `Manager` is an
  `Employee`, `AnnualLeavePolicy` is a `LeavePolicy`, and `EmailNotifier` is a `Notifier`.
- **Composition** is used where one thing uses another: `LeaveService` has a repository,
  policies and notifiers. Any of them can be swapped without changing the service.
- **One policy per leave type:** the brief describes a service with a policy. Because there
  are three leave types, the service holds one policy for each and picks the right one per request.
- **Free text is never logged:** `@audit` writes leave reasons, rejection notes and
  passwords as `<redacted>`, because a reason can contain health information.
- **Pending days are reserved** at submit time, so two pending requests cannot overspend a balance.
- **The service is async** because notifications use `asyncio.gather`. Making the service
  async also means it will fit a web framework later.
- **A fixed "today" can be passed in** to `LeaveService`, so tests and the demo give the
  same result on any date.
