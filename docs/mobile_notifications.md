# Mobile Notifications API

## GET `/api/mobile/notifications`

Fetch the notification feed for the authenticated driver.

### Query Parameters

| Name | Description |
| ---- | ----------- |
| `page` | Page number (default 1) |
| `pageSize` | Number per page (default 20, max 100) |
| `unreadOnly` | When `true`, returns only unread notifications |
| `since` | ISO-8601 timestamp filter |

### Sample Response

```json
{
  "success": true,
  "notifications": [
    {
      "id": "6ccf1a36-769c-43c0-8b4d-74298c8f5a3e",
      "type": "points_change",
      "title": "Points Added",
      "body": "150 points were credited to your account.",
      "metadata": {
        "deltaPoints": 150,
        "balanceAfter": 1200
      },
      "deliveredVia": "in_app,email",
      "isRead": false,
      "createdAt": "2025-02-11T13:05:00",
      "readAt": null
    }
  ],
  "pagination": {
    "page": 1,
    "pageSize": 20,
    "total": 3,
    "hasMore": false
  }
}
```

## POST `/api/mobile/notifications/mark-read`

Mark one or more notifications as read.

### Payload

```json
{
  "notificationIds": ["..."],
  "markAll": false
}
```

Set `markAll` to `true` to mark every notification for the driver.

## GET `/api/mobile/notifications/preferences`

Returns the driver's notification preferences:

```json
{
  "success": true,
  "preferences": {
    "pointChanges": true,
    "orderConfirmations": true,
    "applicationUpdates": true,
    "ticketUpdates": true,
    "refundWindowAlerts": true,
    "accountStatusChanges": true,
    "sensitiveInfoResets": true,
    "emailEnabled": true,
    "inAppEnabled": true,
    "quietHours": {
      "enabled": false,
      "start": null,
      "end": null
    },
    "lowPoints": {
      "enabled": true,
      "threshold": 100
    }
  }
}
```

## PUT `/api/mobile/notifications/preferences`

Send the same payload shape as the response to update preferences.

## POST `/api/mobile/notifications/test-low-points`

Helper endpoint (only in debug/testing environments) to enqueue a low balance alert for QA.

```json
{
  "balance": 40,
  "threshold": 100
}
```

