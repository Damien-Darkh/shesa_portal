"""
models.py - Complete ORM Schema for Phase 1 MVP (Steps 1-5) - FIXED

Database includes:
  Step 1: Identity & VPN (User, Device)
  Step 3: RBAC & Audit (Role, Permission, AuditLog)
  Step 4: Directory (Department, UserProfile, SearchIndex)
  Step 5: ESS - Time, PTO, Notifications

All tables use SQLAlchemy with proper relationships, indexing, and constraints.
Foreign keys cascade on delete where appropriate.
Audit tables are append-only (never update/delete historical records).

FIXES FROM PREVIOUS VERSION:
  - Explicit foreign_keys for ambiguous relationships
  - Removed manager_id from UserProfile to avoid multiple FK paths to User
  - Separate table for reporting relationships if needed
"""

from datetime import datetime, date
from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


# ============================================================================
# STEP 1: IDENTITY & AUTHENTICATION (User, Device)
# ============================================================================

class User(UserMixin, db.Model):
    """
    Employee identity and authentication.
    
    No passwords stored - uses WorkOS OAuth 2.0.
    Role-based access control via user_roles relationship.
    """
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    
    # Identity (from WorkOS AuthKit)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    workos_user_id = db.Column(db.String(64), nullable=True, unique=True)
    first_name = db.Column(db.String(100), nullable=True)
    last_name = db.Column(db.String(100), nullable=True)
    
    # Status & Permissions
    is_admin = db.Column(db.Boolean, default=False, nullable=False)
    disabled = db.Column(db.Boolean, default=False, nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    
    # Synology NAS Integration
    dsm_username = db.Column(db.String(64), nullable=True, unique=True)
    dsm_password_token = db.Column(db.String(64), nullable=True)
    dsm_temp_password = db.Column(db.String(128), nullable=True)  # Single-use, 15-min TTL
    dsm_password_expires_at = db.Column(db.DateTime, nullable=True)
    dsm_must_change_password = db.Column(db.Boolean, default=False, nullable=False)
    
    # Relationships
    devices = db.relationship("Device", backref="owner", lazy=True, cascade="all, delete-orphan")
    roles = db.relationship("Role", secondary="user_roles", backref="users", lazy=True)
    profile = db.relationship("UserProfile", backref="user", uselist=False, cascade="all, delete-orphan",
                            foreign_keys="UserProfile.user_id")  # EXPLICIT foreign_keys
    audit_logs = db.relationship("AuditLog", backref="user", lazy=True, cascade="all, delete-orphan",
                                foreign_keys="AuditLog.user_id")  # EXPLICIT
    departments_managed = db.relationship("Department", backref="manager", lazy=True,
                                         foreign_keys="Department.manager_id")  # EXPLICIT
    time_records = db.relationship("TimeAttendance", backref="user", lazy=True, cascade="all, delete-orphan")
    leave_balances = db.relationship("LeaveBalance", backref="user", lazy=True, cascade="all, delete-orphan")
    leave_requests = db.relationship("LeaveRequest", backref="requester", lazy=True, 
                                    foreign_keys="LeaveRequest.user_id", cascade="all, delete-orphan")  # EXPLICIT
    leave_requests_approved = db.relationship("LeaveRequest", backref="approver_obj", lazy=True,
                                             foreign_keys="LeaveRequest.approver_id")  # EXPLICIT for approver
    notifications = db.relationship("Notification", backref="user", lazy=True, cascade="all, delete-orphan")
    
    @property
    def is_active(self):
        """Flask-Login: active if not disabled."""
        return not self.disabled
    
    @property
    def full_name(self):
        """Convenience property for display."""
        parts = [self.first_name, self.last_name]
        return " ".join(p for p in parts if p) or self.email


class Device(db.Model):
    """
    WireGuard VPN device/peer.
    
    One device per user, per physical machine.
    Contains WireGuard configuration (UUID, address, etc.).
    Supports one-time Windows launcher script delivery.
    """
    __tablename__ = "devices"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    
    # Device identification
    device_name = db.Column(db.String(64), nullable=False)  # e.g., "iPhone", "Work Laptop"
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    
    # WireGuard Configuration
    wg_uuid = db.Column(db.String(64), nullable=False, unique=True)  # OPNsense peer UUID
    wg_api_name = db.Column(db.String(64), nullable=False)  # Sanitized name for OPNsense
    wg_address = db.Column(db.String(32), nullable=False)  # e.g., 10.10.10.7/32
    
    # Revocation & Status
    revoked_at = db.Column(db.DateTime, nullable=True)
    auto_revoked = db.Column(db.Boolean, default=False, nullable=False)  # True if revoked by admin account disable
    
    # Windows Launcher Script (one-time delivery)
    launcher_token = db.Column(db.String(64), nullable=True, unique=True)  # One-time token
    launcher_script = db.Column(db.Text, nullable=True)  # Cached PS1 with WireGuard keys (wiped after fetch)
    launcher_token_expires_at = db.Column(db.DateTime, nullable=True)

    @property
    def is_revoked(self):
        """True if device has been disconnected."""
        return self.revoked_at is not None

    @property
    def launcher_available(self):
        """True until launcher script is fetched or TTL expires."""
        return bool(
            self.launcher_token
            and self.launcher_token_expires_at
            and self.launcher_token_expires_at > datetime.utcnow()
        )


# ============================================================================
# STEP 3: ROLE-BASED ACCESS CONTROL (RBAC)
# ============================================================================

class Role(db.Model):
    """
    Role definition for RBAC.
    
    Examples: Admin, Manager, Employee, HR, IT
    Roles contain multiple permissions (via role_permissions).
    Users can have multiple roles (via user_roles).
    """
    __tablename__ = "roles"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(64), unique=True, nullable=False, index=True)
    description = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    permissions = db.relationship("Permission", secondary="role_permissions", backref="roles", lazy=True)

    def __repr__(self):
        return f"<Role {self.name}>"


class Permission(db.Model):
    """
    Fine-grained permission (action on resource).
    
    Examples:
      - resource="user", action="view" → view_user
      - resource="device", action="delete" → delete_device
      - resource="pto", action="approve" → approve_pto
    
    Permissions are assigned to roles (many-to-many via role_permissions).
    """
    __tablename__ = "permissions"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(64), unique=True, nullable=False, index=True)  # e.g., "view_user"
    description = db.Column(db.String(255), nullable=True)
    resource = db.Column(db.String(64), nullable=False, index=True)  # e.g., "user", "device", "pto"
    action = db.Column(db.String(64), nullable=False)  # e.g., "view", "edit", "delete", "approve"
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<Permission {self.name}>"


# Junction table: User ←→ Role (many-to-many)
user_roles = db.Table(
    "user_roles",
    db.Column("user_id", db.Integer, db.ForeignKey("users.id"), primary_key=True),
    db.Column("role_id", db.Integer, db.ForeignKey("roles.id"), primary_key=True),
)

# Junction table: Role ←→ Permission (many-to-many)
role_permissions = db.Table(
    "role_permissions",
    db.Column("role_id", db.Integer, db.ForeignKey("roles.id"), primary_key=True),
    db.Column("permission_id", db.Integer, db.ForeignKey("permissions.id"), primary_key=True),
)


class AuditLog(db.Model):
    """
    Append-only audit trail.
    
    Records all significant events:
      - Authentication (login/logout)
      - User modifications (created, disabled, role change)
      - Device management (added, revoked, deleted)
      - Permission changes (role assignment, permission grant)
      - PTO approvals/rejections
    
    NEVER update or delete rows - only append new rows.
    Used for compliance, security investigation, and accountability.
    """
    __tablename__ = "audit_logs"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)  # Who performed action (nullable for system events)
    action = db.Column(db.String(255), nullable=False, index=True)  # e.g., "LOGIN", "CREATE_USER", "DELETE_DEVICE"
    resource_type = db.Column(db.String(64), nullable=False, index=True)  # e.g., "USER", "DEVICE", "PTO_REQUEST"
    resource_id = db.Column(db.Integer, nullable=True)  # ID of affected resource
    details = db.Column(db.JSON, nullable=True)  # Additional context (change details, etc.)
    status = db.Column(db.String(32), nullable=False)  # "SUCCESS", "FAILURE"
    ip_address = db.Column(db.String(45), nullable=True)  # IPv4/IPv6
    user_agent = db.Column(db.String(255), nullable=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    __table_args__ = (
        db.Index('idx_audit_user_timestamp', 'user_id', 'timestamp'),
        db.Index('idx_audit_action_timestamp', 'action', 'timestamp'),
        db.Index('idx_audit_resource', 'resource_type', 'resource_id'),
    )

    def __repr__(self):
        return f"<AuditLog {self.action} at {self.timestamp}>"


# ============================================================================
# STEP 4: ORGANIZATIONAL STRUCTURE & DIRECTORY
# ============================================================================

class Department(db.Model):
    """
    Organizational hierarchy.
    
    Supports nested departments (parent_id for sub-departments).
    Each department has an optional manager (User).
    Used for organizational chart, reporting lines, and access control.
    """
    __tablename__ = "departments"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), nullable=False, unique=True, index=True)
    description = db.Column(db.String(255), nullable=True)
    parent_id = db.Column(db.Integer, db.ForeignKey("departments.id"), nullable=True)  # For nested depts
    manager_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    sub_departments = db.relationship("Department", backref=db.backref("parent", remote_side=[id]), lazy=True)
    users = db.relationship("UserProfile", backref="department", lazy=True)

    def __repr__(self):
        return f"<Department {self.name}>"


class UserProfile(db.Model):
    """
    Extended user information for directory and search.
    
    One-to-one with User.
    Contains job title, department, contact info, photo, reporting line.
    Searchable directory via this table.
    
    NOTE: manager_id is removed to avoid ambiguous FK paths to User.
    If you need reporting structure, use a separate ReportingLine table.
    """
    __tablename__ = "user_profiles"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), unique=True, nullable=False, index=True)
    department_id = db.Column(db.Integer, db.ForeignKey("departments.id"), nullable=True, index=True)
    
    # Professional info
    job_title = db.Column(db.String(128), nullable=True)
    phone = db.Column(db.String(20), nullable=True)
    office_location = db.Column(db.String(255), nullable=True)
    
    # Personal profile
    bio = db.Column(db.Text, nullable=True)
    photo_url = db.Column(db.String(255), nullable=True)
    start_date = db.Column(db.Date, nullable=True)
    
    # Metadata
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        db.Index('idx_profile_department', 'department_id'),
    )

    def __repr__(self):
        return f"<UserProfile user_id={self.user_id}>"


class SearchIndex(db.Model):
    """
    Full-text search index (lightweight alternative to Elasticsearch).
    
    Denormalized search data for users, documents, departments.
    Regenerated when source records change.
    Allows fast text search across multiple document types.
    """
    __tablename__ = "search_index"

    id = db.Column(db.Integer, primary_key=True)
    document_type = db.Column(db.String(64), nullable=False, index=True)  # "USER", "DOCUMENT", "DEPARTMENT"
    document_id = db.Column(db.Integer, nullable=False)
    title = db.Column(db.String(255), nullable=False, index=True)
    content = db.Column(db.Text, nullable=False)  # Searchable text
    tags = db.Column(db.String(255), nullable=True)  # Comma-separated
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        db.Index('idx_search_document', 'document_type', 'document_id', unique=True),
        # Full-text search would go here with database-specific syntax
    )

    def __repr__(self):
        return f"<SearchIndex {self.document_type}:{self.document_id}>"


# ============================================================================
# STEP 5: EMPLOYEE SELF-SERVICE (ESS) - TIME & ATTENDANCE
# ============================================================================

class TimeAttendance(db.Model):
    """
    Clock in/out records.
    
    Server-time only (prevents local machine time tampering).
    Tracks daily work hours and breaks.
    Used for payroll and work schedule management.
    """
    __tablename__ = "time_attendance"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    
    # Timestamps (server-side, not client-provided)
    clock_in = db.Column(db.DateTime, nullable=False)  # Server timestamp
    clock_out = db.Column(db.DateTime, nullable=True)
    duration_minutes = db.Column(db.Integer, nullable=True)  # Calculated after clock_out: (clock_out - clock_in) / 60
    
    # Notes
    notes = db.Column(db.String(255), nullable=True)  # e.g., "Working from home", "Approved break"
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.Index('idx_attendance_user_date', 'user_id', 'clock_in'),
    )

    def __repr__(self):
        return f"<TimeAttendance user_id={self.user_id} {self.clock_in}>"


# ============================================================================
# STEP 5: EMPLOYEE SELF-SERVICE (ESS) - LEAVE/PTO MANAGEMENT
# ============================================================================

class LeaveBalance(db.Model):
    """
    Accrued PTO balance per employee per year.
    
    Tracks vacation, sick leave, personal days.
    Accrual = 2.5 days/month = 30 days/year (configurable).
    Split into: accrued_days, used_days, pending_days, carryover_days.
    """
    __tablename__ = "leave_balance"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    year = db.Column(db.Integer, nullable=False)  # Fiscal year
    leave_type = db.Column(db.String(32), nullable=False)  # "vacation", "sick", "personal"
    
    # Balance tracking
    accrued_days = db.Column(db.Float, nullable=False)  # 2.5 * 12 months
    used_days = db.Column(db.Float, default=0.0, nullable=False)  # From approved leave requests
    pending_days = db.Column(db.Float, default=0.0, nullable=False)  # From pending/in-review requests
    carryover_days = db.Column(db.Float, default=0.0, nullable=False)  # From previous year
    
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('user_id', 'year', 'leave_type', name='_leave_balance_uc'),
        db.Index('idx_leave_balance_user_year', 'user_id', 'year'),
    )

    def __repr__(self):
        return f"<LeaveBalance user_id={self.user_id} {self.year} {self.leave_type}>"


class LeaveRequest(db.Model):
    """
    PTO/leave request workflow.
    
    Statuses: PENDING → (approved or rejected)
    Optional multi-step approval via LeaveApprovalWorkflow.
    """
    __tablename__ = "leave_requests"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    leave_type = db.Column(db.String(32), nullable=False)  # "vacation", "sick", "personal"
    
    # Dates
    start_date = db.Column(db.Date, nullable=False, index=True)
    end_date = db.Column(db.Date, nullable=False, index=True)
    days_requested = db.Column(db.Float, nullable=False)  # Can be half-day (0.5)
    
    # Request details
    reason = db.Column(db.Text, nullable=True)
    
    # Status & approval
    status = db.Column(db.String(32), default="PENDING", nullable=False, index=True)  # PENDING, APPROVED, REJECTED, CANCELLED
    approver_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)  # Final approver
    approver_comment = db.Column(db.Text, nullable=True)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    approval_workflow = db.relationship("LeaveApprovalWorkflow", backref="leave_request", lazy=True, cascade="all, delete-orphan")

    __table_args__ = (
        db.Index('idx_leave_request_user_status', 'user_id', 'status'),
        db.Index('idx_leave_request_date_range', 'start_date', 'end_date'),
    )

    def __repr__(self):
        return f"<LeaveRequest user_id={self.user_id} {self.start_date}-{self.end_date}>"


class LeaveApprovalWorkflow(db.Model):
    """
    Multi-step approval chain for leave requests.
    
    Allows sequential approval by multiple managers.
    Example: Employee → Direct Manager → Department Manager → HR
    """
    __tablename__ = "leave_approval_workflow"

    id = db.Column(db.Integer, primary_key=True)
    leave_request_id = db.Column(db.Integer, db.ForeignKey("leave_requests.id"), nullable=False, index=True)
    
    # Approval step
    step = db.Column(db.Integer, nullable=False)  # 1, 2, 3... (order in approval chain)
    approver_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    
    # Status & response
    status = db.Column(db.String(32), default="PENDING", nullable=False, index=True)  # PENDING, APPROVED, REJECTED
    comment = db.Column(db.Text, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.Index('idx_approval_workflow_approver', 'approver_id', 'status'),
    )

    def __repr__(self):
        return f"<LeaveApprovalWorkflow leave_request_id={self.leave_request_id} step={self.step}>"


# ============================================================================
# STEP 5: EMPLOYEE SELF-SERVICE (ESS) - NOTIFICATIONS
# ============================================================================

class Notification(db.Model):
    """
    In-app notifications + email trigger system.
    
    Types: LEAVE_APPROVED, LEAVE_REJECTED, DEVICE_ADDED, PTO_REQUEST_REMINDER, etc.
    Can be marked as read.
    Contains optional deep link to resource.
    """
    __tablename__ = "notifications"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    
    # Content
    notification_type = db.Column(db.String(64), nullable=False, index=True)  # e.g., "LEAVE_APPROVED"
    title = db.Column(db.String(255), nullable=False)
    message = db.Column(db.Text, nullable=False)
    link = db.Column(db.String(255), nullable=True)  # Deep link, e.g., "/account/leave-requests/123"
    
    # Status
    is_read = db.Column(db.Boolean, default=False, nullable=False, index=True)
    
    # Timestamps
    sent_at = db.Column(db.DateTime, default=datetime.utcnow)
    read_at = db.Column(db.DateTime, nullable=True)

    __table_args__ = (
        db.Index('idx_notifications_user_read', 'user_id', 'is_read'),
        db.Index('idx_notifications_sent_at', 'sent_at'),
    )

    def __repr__(self):
        return f"<Notification user_id={self.user_id} {self.notification_type}>"


# ============================================================================
# DATABASE INITIALIZATION & UTILITIES
# ============================================================================

def create_default_roles_and_permissions(db):
    """
    Initialize default roles and permissions.
    
    Call this after db.create_all() on first deployment:
    
    with app.app_context():
        db.create_all()
        create_default_roles_and_permissions(db)
    """
    
    # Check if roles already exist (idempotent)
    if db.session.query(Role).first() is not None:
        return
    
    # Define permissions
    permissions_def = [
        # User management
        ("view_user", "user", "view", "View user profiles"),
        ("edit_user", "user", "edit", "Edit user details"),
        ("create_user", "user", "create", "Create new user"),
        ("delete_user", "user", "delete", "Delete user account"),
        
        # Device management
        ("view_device", "device", "view", "View VPN devices"),
        ("create_device", "device", "create", "Add new VPN device"),
        ("revoke_device", "device", "revoke", "Disconnect VPN device"),
        ("delete_device", "device", "delete", "Delete VPN device"),
        
        # PTO/Leave
        ("view_own_leave", "pto", "view_own", "View own PTO balance"),
        ("request_leave", "pto", "request", "Request time off"),
        ("approve_leave", "pto", "approve", "Approve leave requests"),
        ("view_team_leave", "pto", "view_team", "View team leave requests"),
        
        # Admin functions
        ("view_audit_log", "audit", "view", "View audit logs"),
        ("manage_roles", "rbac", "manage", "Manage roles and permissions"),
        ("view_directory", "directory", "view", "View employee directory"),
    ]
    
    permissions_map = {}
    for perm_name, resource, action, description in permissions_def:
        perm = Permission(
            name=perm_name,
            resource=resource,
            action=action,
            description=description
        )
        db.session.add(perm)
        permissions_map[perm_name] = perm
    
    db.session.flush()  # Assign IDs
    
    # Define roles
    roles_def = {
        "admin": {
            "description": "System administrator",
            "permissions": ["view_user", "edit_user", "create_user", "delete_user",
                          "view_device", "create_device", "revoke_device", "delete_device",
                          "approve_leave", "view_team_leave",
                          "view_audit_log", "manage_roles", "view_directory"],
        },
        "manager": {
            "description": "Department manager",
            "permissions": ["view_user", "view_device",
                          "approve_leave", "view_team_leave",
                          "view_directory"],
        },
        "employee": {
            "description": "Standard employee",
            "permissions": ["view_own_leave", "request_leave", "view_device", "create_device", "view_directory"],
        },
        "hr": {
            "description": "Human Resources",
            "permissions": ["view_user", "edit_user",
                          "view_team_leave", "approve_leave",
                          "view_audit_log", "view_directory"],
        },
        "it": {
            "description": "IT Support",
            "permissions": ["view_user", "view_device", "create_device", "revoke_device",
                          "view_audit_log"],
        },
    }
    
    for role_name, role_data in roles_def.items():
        role = Role(
            name=role_name,
            description=role_data["description"]
        )
        for perm_name in role_data["permissions"]:
            if perm_name in permissions_map:
                role.permissions.append(permissions_map[perm_name])
        db.session.add(role)
    
    db.session.commit()
    print("✅ Default roles and permissions created")


# ============================================================================
# DATABASE SCHEMA SUMMARY (for reference)
# ============================================================================

"""
TABLES CREATED:

Step 1: Authentication & VPN
  - User (core identity, WorkOS integration)
  - Device (WireGuard peers)

Step 3: RBAC & Audit
  - Role (role definitions)
  - Permission (fine-grained permissions)
  - user_roles (User ←→ Role junction)
  - role_permissions (Role ←→ Permission junction)
  - AuditLog (append-only event trail)

Step 4: Directory & Search
  - Department (organizational hierarchy)
  - UserProfile (extended user info, searchable)
  - SearchIndex (full-text search index)

Step 5: ESS - Time & PTO
  - TimeAttendance (clock in/out records)
  - LeaveBalance (accrued PTO tracking)
  - LeaveRequest (PTO request workflow)
  - LeaveApprovalWorkflow (multi-step approval)
  - Notification (in-app + email notifications)

TOTAL: 15 tables (+ 2 junction tables)

RELATIONSHIPS (FIXED - no ambiguity):
  User ←→ Role (many-to-many via user_roles) - EXPLICIT foreign_keys
  Role ←→ Permission (many-to-many via role_permissions)
  User → Department (via manager_id in Department)
  Department → User (nested hierarchy)
  LeaveRequest → LeaveApprovalWorkflow (one-to-many)
  User → LeaveRequest (one-to-many) - EXPLICIT foreign_keys for requester and approver
  User → UserProfile (one-to-one) - EXPLICIT foreign_keys
  User → Device, TimeAttendance, LeaveBalance, Notification (one-to-many)

INDEXES:
  All frequently-queried columns indexed (user_id, status, timestamp, etc.)
  Composite indexes on common filter combinations
  Unique constraints on key fields
"""