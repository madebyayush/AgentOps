import logging

logger = logging.getLogger("agentops.security.rbac")

class RBACGuard:
    """
    Role-Based Access Control (RBAC) and Security Clearance Guard.
    Ensures that agent activities are constrained by the issuing client clearance.
    """
    def __init__(self):
        # Operational clearances: Higher value requires more authorized roles.
        self.operation_clearance = {
            "query_semantic_memory": 1,
            "invoke_basic_tool": 2,
            "execute_filesystem_ops": 3,
            "destroy_databases": 5
        }
        logger.info("RBAC Guard module configured.")

    def authorize(self, user_roles: list[str], target_op: str) -> bool:
        """
        Validates permission scopes.
        Roles map:
        - admin: level 5 clearance
        - operator: level 3 clearance
        - auditor: level 1 clearance
        """
        required_clearance = self.operation_clearance.get(target_op, 5)
        
        # Determine maximum clearance score for the user roles
        max_clearance = 0
        for role in user_roles:
            role_lower = role.lower()
            if role_lower == "admin":
                max_clearance = max(max_clearance, 5)
            elif role_lower == "operator":
                max_clearance = max(max_clearance, 3)
            elif role_lower == "auditor":
                max_clearance = max(max_clearance, 1)
                
        is_authorized = max_clearance >= required_clearance
        
        if not is_authorized:
            logger.warning(
                f"Security Authorization Failed! Roles {user_roles} "
                f"insufficient for target action '{target_op}' (Req: {required_clearance}, Has: {max_clearance})."
            )
        else:
            logger.debug(f"RBAC authorization granted for operations: '{target_op}'")
            
        return is_authorized
