# Driver Rewards Platform - Comprehensive Project Summary

## Project Overview

This is a full-stack driver rewards platform that enables sponsor companies to incentivize their drivers through a points-based reward system. Drivers can earn points from sponsors and redeem them for products from integrated catalogs (primarily eBay). The platform includes a Flask-based web application and an Android mobile app, serving three distinct user roles: Drivers, Sponsors, and Administrators.

---

## Architecture & Technology Stack

### Backend
- **Framework**: Flask (Python 3.9+)
- **Database**: MySQL with SQLAlchemy ORM
- **Authentication**: Flask-Login with session management
- **Security**: Flask-WTF CSRF protection, bcrypt password hashing
- **API**: RESTful API for mobile app integration
- **Performance**: Flask-Compress (gzip), orjson for JSON serialization

### Frontend
- **Web**: Jinja2 templates with Bootstrap/CSS
- **Mobile**: Native Android app (Kotlin) with Material Design
- **Architecture**: MVVM pattern on mobile, traditional MVC on web

### Cloud Services
- **AWS S3**: Profile picture storage with presigned URLs for secure access
- **eBay API**: Product catalog integration (Browse API v1)
- **Email Services**: 
  - Ethereal Mail for notifications
  - MailTrap for password resets and other transactional emails

### Database
- **MySQL**: Relational database with comprehensive schema
- **Migrations**: Flask-Migrate (Alembic) for schema versioning
- **Connection Pooling**: SQLAlchemy with connection pooling and pre-ping

---

## Core Features

### 1. User Roles & Authentication

#### Three User Types:
- **Drivers**: Earn and redeem points, browse catalogs, submit applications
- **Sponsors**: Manage drivers, award points, configure catalogs, review applications
- **Admins**: System-wide administration, user management, support ticket handling

#### Authentication Features:
- Email/password authentication with bcrypt hashing (12 rounds)
- Multi-Factor Authentication (MFA) using TOTP (Time-based One-Time Password)
- Email verification required for new accounts
- Account lockout after failed login attempts (5 attempts within 15 minutes)
- Password reset via magic links (token-based)
- Session management with device tracking
- Remember me functionality (31-day sessions)

### 2. Security Measures

#### Authentication & Authorization:
- **Password Security**:
  - Bcrypt hashing with 12 rounds
  - Password strength validation (min 8 chars, uppercase, lowercase, number, special char)
  - Password history tracking (prevents reuse of last 5 passwords)
  - Password change audit trail with IP address and user agent logging
  
- **Account Protection**:
  - Account lockout after 5 failed login attempts (15-minute window)
  - Email verification requirement
  - Account status management (Active, Inactive, Pending, Rejected, Archived)
  - MFA support with recovery codes
  
- **Session Security**:
  - Tracked sessions stored in database
  - Device fingerprinting (browser, OS, device type)
  - IP address tracking
  - Auto-logout after 30 minutes of inactivity
  - Session expiration after 24 hours
  - Multiple concurrent sessions support
  
- **CSRF Protection**:
  - Flask-WTF CSRF tokens on all POST/PUT/PATCH/DELETE requests
  - 31-day token expiration to match session lifetime
  - Double-submit cookie pattern for AJAX requests
  - Mobile API exempted (uses separate authentication)

#### Data Protection:
- **Encryption**:
  - Fernet (symmetric encryption) for sensitive fields:
    - Phone numbers
    - License numbers
    - License issue/expiration dates
    - MFA secrets
  
- **Input Validation**:
  - Comprehensive input sanitization (SQL injection prevention)
  - Regex validation for emails, phone numbers, UUIDs, dates
  - XSS prevention through template escaping
  - SQL LIKE pattern sanitization

#### Security Headers:
- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: DENY`
- `X-XSS-Protection: 1; mode=block`
- `Strict-Transport-Security: max-age=31536000; includeSubDomains`
- `Referrer-Policy: strict-origin-when-cross-origin`
- `Content-Security-Policy` with S3 domain allowlist

#### Rate Limiting:
- Login attempt rate limiting
- API endpoint protection

#### Audit Trails:
- Login attempts logging (success/failure, IP, timestamp)
- Password change history
- Profile change auditing (Driver, Sponsor, Admin profiles)
- Point change tracking with actor identification
- Session activity logging

### 3. Points System

#### Multi-Environment Points:
- Drivers can belong to multiple sponsors (environments)
- Each driver-sponsor relationship has its own points balance
- Environment-specific point transactions
- Point balance isolation between sponsors

#### Point Transactions:
- **Award Points**: Sponsors can add points to driver accounts
- **Deduct Points**: Sponsors can remove points (with reason tracking)
- **Order Deductions**: Points deducted automatically when orders are placed
- **Challenge Rewards**: Points awarded for completing challenges
- **Achievement Rewards**: Points-based achievements
- **Refunds**: Point refunds for cancelled orders within refund window

#### Point Change Tracking:
- Complete audit trail for all point changes
- Actor identification (who performed the change)
- Reason tracking for all transactions
- Impersonation tracking (admin actions on behalf of users)
- Balance snapshots (balance before/after each transaction)
- Dispute system for drivers to contest point changes

#### Point Settings:
- Company-wide point-to-dollar conversion rate
- Per-transaction minimum and maximum limits
- Configurable at sponsor company level

### 4. Product Catalog Integration

#### eBay Integration:
- **API**: eBay Browse API v1 (Production and Sandbox environments)
- **OAuth**: Application-level OAuth tokens with auto-refresh
- **Product Search**: Keyword and category-based search
- **Product Details**: Full item information, pricing, availability
- **Safe Search**: Configurable adult content filtering
- **Caching**: Product data caching to reduce API calls

#### Catalog Features:
- **Sponsor Catalog**: eBay products filtered and curated for sponsors
- **Driver Catalog**: Points-based catalog view for drivers
- **Pagination**: Efficient pagination (default 48 items per page)
- **Filtering**: Category, price range, availability filters
- **Favorites**: Drivers can favorite products
- **Product Views**: Track driver product viewing for analytics
- **Stock Management**: Low stock alerts and availability tracking

### 5. Shopping Cart & Orders

#### Cart System:
- Persistent shopping carts per driver
- Multi-item support with quantities
- External catalog item storage (eBay item details)
- Points calculation and validation
- Cart item management (add, update, remove)

#### Order Processing:
- Order creation from cart items
- Points deduction validation
- Order numbering system
- Order status tracking (pending, processing, shipped, delivered, cancelled)
- Line item tracking
- Order cancellation with refund windows
- Sponsor invoice generation

#### Shipping Integration:
- Shipping service integration (prepared for external shipping APIs)
- Order tracking support

### 6. Driver Applications

#### Application Process:
- Drivers submit applications to sponsor companies
- Comprehensive application form:
  - CDL class (A, B, C)
  - Experience (years/months)
  - Transmission preference
  - Violations and incidents tracking
  - License information (encrypted)
  - Electronic signature
- Application status tracking (pending, accepted, rejected)

#### Sponsor Review:
- Sponsors review and make decisions on applications
- Accept/reject with reason tracking
- Automatic driver account creation upon acceptance
- Driver-sponsor environment setup upon approval

### 7. Challenges & Achievements

#### Challenges:
- **Challenge Templates**: Reusable challenge definitions
- **Sponsor Challenges**: Sponsor-specific challenges with custom rewards
- **Challenge Subscriptions**: Drivers subscribe to challenges
- **Challenge Completion**: Status tracking (subscribed, completed, expired)
- **Reward Points**: Configurable point rewards per challenge
- **Time-based**: Start and expiration dates

#### Achievements:
- **Achievement System**: Points-based and milestone achievements
- **Driver Achievements**: Track earned achievements per driver
- **Achievement Service**: Automated achievement checking and awarding

### 8. Notifications System

#### Notification Types:
- **Point Changes**: Notifications when points are added/deducted
- **Order Confirmations**: Order placement and status updates
- **Application Updates**: Application status changes
- **Ticket Updates**: Support ticket responses
- **Refund Window Alerts**: Warnings before refund window closes
- **Account Status Changes**: Account activation/deactivation notices
- **Sensitive Info Resets**: Password/reset notifications

#### Delivery Channels:
- **Email**: SMTP via Ethereal Mail (notifications) and MailTrap (transactional)
- **In-App**: Database-stored notifications with read/unread status
- **Mobile Push**: Prepared for push notifications (Android)

#### Notification Preferences:
- **Driver Preferences**: Granular control over notification types
- **Quiet Hours**: Configurable do-not-disturb windows
- **Low Points Alerts**: Configurable threshold for balance warnings
- **Critical Notifications**: Always sent (account status, security)
- **Sponsor Preferences**: Sponsor-specific notification settings
- **Admin Preferences**: System alert preferences

### 9. Support Ticket System

#### Ticket Features:
- Multi-role support (drivers, sponsors, admins)
- Ticket categories
- Status tracking (new, open, waiting, resolved, closed)
- Message threads per ticket
- Role-based access control

### 10. Profile Management

#### Driver Profiles:
- Personal information (name, email, phone - encrypted)
- Shipping address
- License information (encrypted storage)
- Profile pictures (AWS S3 with presigned URLs)
- Points goal tracking
- Notification preferences

#### Sponsor Profiles:
- Company information
- Billing details
- Point settings (rates, limits)
- Catalog configuration
- Driver management

#### Admin Profiles:
- Administrative access
- System configuration
- User management capabilities

#### Profile Auditing:
- Complete audit trail for profile changes
- Field-level change tracking
- Change reason tracking
- Actor identification

### 11. Leaderboard

- Driver ranking system
- Points-based leaderboards
- Sponsor-specific leaderboards

### 12. Invoice System

#### Sponsor Invoicing:
- Monthly invoice generation
- Aggregate order data
- Point-to-dollar conversion
- Invoice status tracking (pending, paid, overdue)
- Invoice line items with order details

---

## Mobile App Integration

### Android App Architecture

#### Technology Stack:
- **Language**: Kotlin
- **Architecture**: MVVM (Model-View-ViewModel)
- **Networking**: Retrofit for API calls
- **Authentication**: Session-based with credential storage
- **UI**: Material Design components, RecyclerViews, Fragments

#### Key Features:
- **Authentication**: Login, MFA verification, session management
- **Catalog Browsing**: Product list, categories, search, favorites
- **Product Details**: Full product information, add to cart
- **Shopping Cart**: View cart, update quantities, checkout
- **Orders**: Order history, order details, tracking
- **Points**: Balance display, transaction history, points goal
- **Notifications**: Notification feed, preferences, read/unread status
- **Profile**: View/edit profile, change password, update address
- **Biometric Auth**: Fingerprint/face unlock support

#### API Integration:
- RESTful API endpoints under `/api/mobile/*`
- JSON request/response format
- Session-based authentication
- CSRF exemption for mobile endpoints
- Error handling and retry logic

#### Mobile-Specific Endpoints:
- `/api/mobile/login` - Mobile-optimized login
- `/api/mobile/mfa/verify` - MFA code verification
- `/api/mobile/catalog` - Product catalog with pagination
- `/api/mobile/cart` - Cart management
- `/api/mobile/orders` - Order history and details
- `/api/mobile/points` - Points balance and transactions
- `/api/mobile/notifications` - Notification feed
- `/api/mobile/profile` - Profile management
- `/api/mobile/favorites` - Favorite products management

---

## Database Schema Overview

### Core Tables:
- **Account**: Base user accounts with authentication info
- **Driver**: Driver-specific information
- **Sponsor**: Sponsor account information
- **SponsorCompany**: Company-level settings and billing
- **Admin**: Administrative accounts
- **DriverSponsor**: Many-to-many relationship (environments) with points balances

### Transaction Tables:
- **PointChanges**: Complete point transaction history
- **Orders**: Order records
- **OrderLineItem**: Order line items
- **Cart** / **CartItem**: Shopping cart storage

### Application & Relationship Tables:
- **Application**: Driver applications to sponsors
- **DriverSponsor**: Driver-sponsor environment relationships

### Catalog Tables:
- **Products**: Cached product information
- **DriverProductView**: Product viewing analytics

### Challenge & Achievement Tables:
- **ChallengeTemplate**: Reusable challenge definitions
- **SponsorChallenge**: Sponsor-specific challenges
- **DriverChallengeSubscription**: Driver challenge participation
- **Achievement**: Achievement definitions
- **DriverAchievement**: Driver achievement records

### Notification Tables:
- **DriverNotification**: Individual notifications
- **NotificationPreferences**: Driver notification settings
- **SponsorNotificationPreferences**: Sponsor notification settings
- **AdminNotificationPreferences**: Admin notification settings

### Audit & Security Tables:
- **LoginAttempts**: Login attempt logging
- **PasswordHistory**: Password change history
- **UserSessions**: Active session tracking
- **DriverProfileAudit**: Driver profile change audit
- **SponsorProfileAudit**: Sponsor profile change audit
- **AdminProfileAudit**: Admin profile change audit
- **PointChangeDispute**: Point change dispute records

### Support Tables:
- **SupportTicket**: Support ticket records
- **SupportMessage**: Ticket messages
- **SupportCategory**: Ticket categories

### Billing Tables:
- **SponsorInvoice**: Monthly sponsor invoices
- **SponsorInvoiceOrder**: Invoice line items

---

## API Architecture

### Web API:
- Traditional Flask routes with Jinja2 templates
- Form-based submissions with CSRF protection
- AJAX endpoints for dynamic content
- RESTful principles where applicable

### Mobile API:
- RESTful JSON API under `/api/mobile/*`
- Consistent response format: `{"success": bool, "data": {...}, "message": "..."}`
- Error handling with appropriate HTTP status codes
- Pagination support for list endpoints
- Filtering and sorting capabilities

### Authentication Flow:
1. User submits credentials to `/api/mobile/login`
2. Server validates and checks MFA status
3. If MFA enabled, returns MFA challenge
4. User submits MFA code to `/api/mobile/mfa/verify`
5. Server creates session and returns session token
6. Mobile app stores session token for subsequent requests
7. Flask-Login manages web session state

---

## Security Implementation Details

### Encryption:
- **Fernet (Symmetric)**: Used for sensitive field encryption
  - Phone numbers
  - License information
  - MFA secrets
- **Bcrypt (Hashing)**: Password storage with 12 rounds

### Session Management:
- Database-backed sessions (not just cookies)
- Device fingerprinting
- IP address tracking
- Activity-based expiration (30 min inactivity)
- Absolute expiration (24 hours)
- Multiple concurrent sessions supported

### Input Validation:
- SQL injection prevention through parameterized queries (SQLAlchemy)
- XSS prevention through template escaping
- Regex validation for all user inputs
- Length limits on all string fields
- Type validation

### Authorization:
- Role-based access control (RBAC)
- Route-level decorators for role checking
- Resource-level permissions (e.g., drivers can only see their own data)
- Sponsor isolation (sponsors can only manage their drivers)

### Security Headers:
- Comprehensive security headers on all responses
- CSP (Content Security Policy) with S3 allowlist
- HSTS (HTTP Strict Transport Security)
- X-Frame-Options to prevent clickjacking
- X-Content-Type-Options to prevent MIME sniffing

---

## Cloud Services Integration

### AWS S3:
- **Purpose**: Profile picture storage
- **Security**: Private bucket with presigned URLs
- **Authentication**: IAM roles or access keys
- **URL Expiration**: Configurable (default 1 hour)
- **File Validation**: Allowed extensions (.png, .jpg, .jpeg, .gif, .webp, .ico)
- **Size Limit**: 5MB maximum

### eBay API:
- **Integration**: Browse API v1
- **OAuth**: Application-level OAuth tokens
- **Environments**: Production and Sandbox support
- **Token Management**: Auto-refresh mechanism
- **Error Handling**: Robust error handling with retry logic
- **Caching**: Product data caching to reduce API calls
- **Rate Limiting**: Respects eBay API rate limits

### Email Services:
- **Ethereal Mail**: Notification emails (driver notifications, order confirmations)
- **MailTrap**: Password resets, account verification, transactional emails
- **TLS**: All email connections use TLS encryption

---

## Performance Optimizations

### Backend:
- **Connection Pooling**: SQLAlchemy connection pooling with pre-ping
- **Query Optimization**: Eager loading (joinedload) to reduce N+1 queries
- **Caching**: Product catalog caching (10-minute TTL)
- **Compression**: Flask-Compress for gzip compression
- **JSON Serialization**: orjson for faster JSON encoding/decoding
- **Database Indexing**: Strategic indexes on frequently queried fields

### Frontend:
- **Lazy Loading**: Images and content loaded on demand
- **Pagination**: Efficient pagination to limit data transfer
- **Caching**: Browser caching for static assets
- **Minification**: CSS/JS minification (production)

### Mobile:
- **Pagination**: Efficient list pagination
- **Image Caching**: Product image caching
- **Background Sync**: Notification polling worker
- **Offline Support**: Prepared for offline functionality

---

## Deployment Considerations

### Environment Variables:
- Database credentials
- AWS credentials and S3 bucket configuration
- eBay API credentials and environment
- Secret keys (Flask secret, encryption key)
- Email service credentials
- Feature flags

### Database Migrations:
- Alembic migrations for schema changes
- Version-controlled migration files
- Rollback capability

### Session Storage:
- Database-backed sessions (production-ready)
- Can be migrated to Redis for horizontal scaling

### Static Files:
- Profile pictures: AWS S3
- Web static files: Served by Flask (can use CDN)
- Mobile assets: Bundled in APK

---

## Testing

### Test Coverage:
- Achievement service tests
- Challenge service tests
- Driver notification tests
- Fast mode tests
- SQL injection protection tests

### Test Framework:
- Python unittest framework
- Test database setup/teardown

---

## Key Design Decisions

### 1. Multi-Environment Points System:
- Drivers can belong to multiple sponsors
- Each relationship has independent point balance
- Allows drivers to work with multiple companies

### 2. Database-Backed Sessions:
- Enables session management across multiple servers
- Provides audit trail for security
- Supports device tracking and remote logout

### 3. Fernet Encryption for Sensitive Fields:
- Symmetric encryption for fields that need to be decrypted
- Phone numbers and license info need to be readable
- MFA secrets need decryption for verification

### 4. Two Email Services:
- Ethereal Mail for notifications (development-friendly)
- MailTrap for transactional emails (password resets)
- Allows separate configuration and monitoring

### 5. CSRF Exemption for Mobile API:
- Mobile apps don't use cookies for CSRF
- Session-based authentication is sufficient
- Reduces complexity for mobile developers

### 6. Presigned URLs for S3:
- Private bucket security
- Time-limited access
- No direct S3 credentials needed in frontend

### 7. Comprehensive Audit Trails:
- All critical actions are logged
- Enables compliance and debugging
- Provides transparency for users

---

## Future Enhancement Opportunities

1. **Push Notifications**: Implement Firebase Cloud Messaging for mobile push notifications
2. **Redis Sessions**: Migrate to Redis for session storage in multi-server deployments
3. **Real-time Updates**: WebSocket support for real-time notifications
4. **Advanced Analytics**: Dashboard with usage analytics and reporting
5. **Mobile Push Notifications**: Implement background notifications for mobile app
6. **GraphQL API**: Consider GraphQL for more flexible mobile queries
7. **Microservices**: Split into microservices for better scalability
8. **CDN Integration**: Use CDN for static assets and product images
9. **Automated Testing**: Expand test coverage (unit, integration, E2E)
10. **API Rate Limiting**: More granular rate limiting per endpoint

---

## Common Interview Questions & Answers

### Q: Explain the security measures you implemented.

**A**: We implemented comprehensive security at multiple layers:

1. **Authentication**: Bcrypt password hashing (12 rounds), MFA with TOTP, email verification, account lockout after failed attempts
2. **Authorization**: Role-based access control, resource-level permissions, sponsor isolation
3. **Data Protection**: Fernet encryption for sensitive fields (phone, license, MFA secrets), input validation and sanitization
4. **Session Security**: Database-backed sessions, device fingerprinting, IP tracking, auto-logout, activity-based expiration
5. **CSRF Protection**: Flask-WTF CSRF tokens, double-submit cookie pattern
6. **Security Headers**: CSP, HSTS, X-Frame-Options, X-Content-Type-Options
7. **Audit Trails**: Complete logging of login attempts, password changes, profile changes, point transactions

### Q: How does the mobile app communicate with the backend?

**A**: The mobile app uses a RESTful JSON API under `/api/mobile/*`. Authentication is session-based using Flask-Login. The app sends credentials to `/api/mobile/login`, receives a session token, and includes this token in subsequent requests. The API returns JSON responses with a consistent format. Mobile endpoints are exempt from CSRF protection since mobile apps don't use cookies for CSRF. The app uses Retrofit for HTTP requests and handles errors, retries, and pagination.

### Q: Explain the points system architecture.

**A**: The points system uses a multi-environment model. Drivers can belong to multiple sponsors, and each driver-sponsor relationship (stored in `DriverSponsor` table) has its own independent points balance. This allows drivers to work with multiple companies while keeping points separate. All point changes are tracked in the `PointChanges` table with complete audit information: who made the change, when, why, and the balance before/after. Points can be awarded by sponsors, deducted for orders, or awarded through challenges and achievements. There's also a dispute system where drivers can contest point changes.

### Q: How does the eBay integration work?

**A**: We integrate with eBay's Browse API v1 using OAuth application-level tokens. The integration supports both Production and Sandbox environments. OAuth tokens are automatically refreshed to prevent expiration. The `EbayProvider` class handles API calls with robust error handling, retry logic, and connection pooling. Product data is cached (10-minute TTL) to reduce API calls and improve performance. We filter adult content based on category IDs and respect eBay's rate limits. Products are displayed in both sponsor and driver catalogs with points-based pricing.

### Q: Describe the notification system.

**A**: We have a comprehensive notification system with multiple delivery channels (email and in-app). Notifications are stored in the database with read/unread status. Users have granular preferences controlling which notification types they receive and via which channels. Drivers can configure "quiet hours" for non-critical notifications. Critical notifications (account status changes, security events) are always sent. The system supports notifications for points changes, orders, applications, support tickets, refund windows, and more. Email notifications use Ethereal Mail, and the mobile app polls for notifications or can receive push notifications (prepared for implementation).

### Q: How do you handle sensitive data encryption?

**A**: We use Fernet symmetric encryption for fields that need to be decrypted (phone numbers, license info, MFA secrets). Fernet provides authenticated encryption and is implemented through properties on the models that automatically encrypt on write and decrypt on read. Passwords use bcrypt hashing (one-way) with 12 rounds. The encryption key is stored in environment variables and never committed to the codebase. All encrypted fields have plaintext property accessors that handle encryption/decryption transparently.

### Q: Explain session management.

**A**: Sessions are stored in the database (`UserSessions` table) rather than just cookies, enabling multi-server deployments and providing an audit trail. Each session includes device information (browser, OS, device type), IP address, and user agent. Sessions expire after 30 minutes of inactivity or 24 hours absolutely. Users can view and manage their active sessions. The `SessionManagementService` handles session creation, validation, and cleanup. Flask-Login manages the web session state, and we maintain session tokens in the Flask session for tracking.

### Q: How does the application handle multi-tenant data isolation?

**A**: Data isolation is achieved through the `DriverSponsor` relationship table. Each driver-sponsor pair represents an "environment" with its own points balance. Sponsors can only view and manage drivers in their environments. Database queries filter by `SponsorID` or `DriverSponsorID` to ensure sponsors only see their data. Admins have system-wide access but their actions are audited. Role-based decorators on routes enforce authorization checks before allowing access to resources.

---

## Project Structure

```
F25-Team10/
├── flask/                    # Flask backend application
│   ├── app/
│   │   ├── __init__.py      # Flask app factory
│   │   ├── models.py        # SQLAlchemy models
│   │   ├── routes/          # Route blueprints
│   │   ├── services/        # Business logic services
│   │   ├── templates/       # Jinja2 templates
│   │   ├── static/          # CSS, JS, images
│   │   ├── decorators/      # Custom decorators
│   │   ├── utils/           # Utility functions
│   │   └── sponsor_catalog/ # eBay catalog integration
│   ├── config.py            # Configuration
│   ├── security_config.py   # Security utilities
│   ├── requirements.txt     # Python dependencies
│   └── run.py               # Application entry point
├── mobileApplication/        # Android mobile app
│   └── app/
│       └── src/main/
│           ├── java/.../    # Kotlin source code
│           └── res/         # Android resources
└── docs/                    # Documentation
```

---

This summary provides a comprehensive overview of the project, covering architecture, features, security, integrations, and implementation details. Use this document to prepare for interviews and explain your contributions to the project.


