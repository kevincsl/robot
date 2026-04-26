"""Security module tests."""
from __future__ import annotations

import pytest
from pathlib import Path
import tempfile

from robot.security import (
    validate_path_traversal,
    validate_command_args,
    sanitize_file_size,
    sanitize_error_message,
    SecurityError,
)


class TestPathTraversal:
    """Test path traversal validation."""

    def test_valid_path_within_root(self, tmp_path):
        """Valid path within allowed root should pass."""
        allowed_roots = [tmp_path]
        target = tmp_path / "subdir" / "file.txt"

        result = validate_path_traversal(target, allowed_roots, must_exist=False)
        assert result == target.resolve()

    def test_path_traversal_attack(self, tmp_path):
        """Path traversal with .. should be blocked."""
        allowed_roots = [tmp_path / "allowed"]
        target = tmp_path / "allowed" / ".." / ".." / "etc" / "passwd"

        with pytest.raises(SecurityError, match="suspicious pattern"):
            validate_path_traversal(target, allowed_roots, must_exist=False)

    def test_suspicious_pattern_detection(self, tmp_path):
        """Paths with suspicious patterns should be blocked."""
        allowed_roots = [tmp_path]

        # Test various traversal patterns
        suspicious_paths = [
            "../../../etc/passwd",
            "subdir/../../etc/passwd",
            "../../etc/passwd",
        ]

        for path_str in suspicious_paths:
            target = tmp_path / path_str
            with pytest.raises(SecurityError, match="suspicious pattern"):
                validate_path_traversal(target, allowed_roots, must_exist=False)

    def test_absolute_path_outside_root(self, tmp_path):
        """Absolute path outside allowed roots should be blocked."""
        allowed_roots = [tmp_path / "allowed"]
        target = Path("/etc/passwd")

        with pytest.raises(SecurityError, match="outside allowed directories"):
            validate_path_traversal(target, allowed_roots, must_exist=False)

    def test_must_exist_validation(self, tmp_path):
        """Non-existent path should fail when must_exist=True."""
        allowed_roots = [tmp_path]
        target = tmp_path / "nonexistent.txt"

        with pytest.raises(SecurityError, match="does not exist"):
            validate_path_traversal(target, allowed_roots, must_exist=True)

    def test_existing_file_validation(self, tmp_path):
        """Existing file should pass when must_exist=True."""
        allowed_roots = [tmp_path]
        target = tmp_path / "existing.txt"
        target.write_text("test")

        result = validate_path_traversal(target, allowed_roots, must_exist=True)
        assert result == target.resolve()


class TestCommandValidation:
    """Test command argument validation."""

    def test_safe_arguments(self):
        """Safe arguments should pass validation."""
        safe_args = [
            "-t", "user@example.com",
            "-s", "Test Subject",
            "-bdy", "Test body",
        ]

        result = validate_command_args(safe_args)
        assert result == safe_args

    def test_command_injection_semicolon(self):
        """Arguments with semicolons should be blocked."""
        dangerous_args = ["-t", "user@example.com; rm -rf /"]

        with pytest.raises(SecurityError, match="dangerous pattern"):
            validate_command_args(dangerous_args)

    def test_command_injection_pipe(self):
        """Arguments with pipes should be blocked."""
        dangerous_args = ["-t", "user@example.com | cat /etc/passwd"]

        with pytest.raises(SecurityError, match="dangerous pattern"):
            validate_command_args(dangerous_args)

    def test_command_injection_backtick(self):
        """Arguments with backticks should be blocked."""
        dangerous_args = ["-s", "Test `whoami`"]

        with pytest.raises(SecurityError, match="dangerous pattern"):
            validate_command_args(dangerous_args)

    def test_command_substitution(self):
        """Arguments with command substitution should be blocked."""
        dangerous_args = ["-s", "Test $(whoami)"]

        with pytest.raises(SecurityError, match="dangerous pattern"):
            validate_command_args(dangerous_args)

    def test_redirect_to_absolute_path(self):
        """Arguments with redirects to absolute paths should be blocked."""
        dangerous_args = ["-bdy", "content > /etc/passwd"]

        with pytest.raises(SecurityError, match="dangerous pattern"):
            validate_command_args(dangerous_args)

    def test_invalid_email_format(self):
        """Invalid email addresses should be blocked."""
        invalid_emails = [
            "-t", "not-an-email",
            "-t", "missing@domain",
            "-t", "@nodomain.com",
        ]

        with pytest.raises(SecurityError, match="Invalid email format"):
            validate_command_args(invalid_emails)

    def test_valid_email_format(self):
        """Valid email addresses should pass."""
        valid_args = [
            "-t", "user@example.com",
            "-cc", "admin@test.co.uk",
        ]

        result = validate_command_args(valid_args)
        assert result == valid_args


class TestFileSizeValidation:
    """Test file size validation."""

    def test_small_file_passes(self, tmp_path):
        """Small file should pass validation."""
        test_file = tmp_path / "small.txt"
        test_file.write_text("x" * 1024)  # 1KB

        # Should not raise
        sanitize_file_size(test_file, max_size_mb=1)

    def test_large_file_blocked(self, tmp_path):
        """Large file should be blocked."""
        test_file = tmp_path / "large.txt"
        # Create 2MB file
        test_file.write_bytes(b"x" * (2 * 1024 * 1024))

        with pytest.raises(SecurityError, match="File too large"):
            sanitize_file_size(test_file, max_size_mb=1)

    def test_nonexistent_file(self, tmp_path):
        """Non-existent file should raise error."""
        test_file = tmp_path / "nonexistent.txt"

        with pytest.raises(SecurityError, match="does not exist"):
            sanitize_file_size(test_file, max_size_mb=1)

    def test_exact_size_limit(self, tmp_path):
        """File at exact size limit should pass."""
        test_file = tmp_path / "exact.txt"
        # Create exactly 1MB file
        test_file.write_bytes(b"x" * (1024 * 1024))

        # Should not raise
        sanitize_file_size(test_file, max_size_mb=1)


class TestErrorSanitization:
    """Test error message sanitization."""

    def test_path_redaction(self, tmp_path):
        """Absolute paths should be redacted."""
        project_root = tmp_path / "project"
        error_msg = f"Error in file: {project_root}/secret/file.txt"

        result = sanitize_error_message(error_msg, project_root)
        assert str(project_root) not in result
        assert "<project_root>" in result

    def test_home_directory_redaction(self):
        """Home directory paths should be redacted."""
        home = Path.home()
        error_msg = f"Error in file: {home}/secret/file.txt"

        result = sanitize_error_message(error_msg, Path("/tmp"))
        assert str(home) not in result
        assert "~" in result

    def test_token_redaction(self):
        """Long tokens should be redacted."""
        error_msg = "API error: token abc123def456ghi789jkl012mno345pqr678"

        result = sanitize_error_message(error_msg, Path("/tmp"))
        assert "abc123def456ghi789jkl012mno345pqr678" not in result
        assert "<REDACTED>" in result

    def test_quoted_token_redaction(self):
        """Quoted tokens should be redacted."""
        error_msg = 'API error: token "abc123def456ghi789jkl012mno345pqr678"'

        result = sanitize_error_message(error_msg, Path("/tmp"))
        assert "abc123def456ghi789jkl012mno345pqr678" not in result
        assert "<REDACTED>" in result

    def test_normal_text_preserved(self):
        """Normal error text should be preserved."""
        error_msg = "Connection timeout after 30 seconds"

        result = sanitize_error_message(error_msg, Path("/tmp"))
        assert result == error_msg


class TestIntegration:
    """Integration tests combining multiple security features."""

    def test_sendmail_args_full_validation(self):
        """Test full sendmail argument validation flow."""
        # Valid sendmail arguments
        valid_args = [
            "-t", "user@example.com",
            "-s", "Test Subject",
            "-bdy", "Test body content",
        ]

        result = validate_command_args(valid_args)
        assert result == valid_args

    def test_file_path_and_size_validation(self, tmp_path):
        """Test combined path and size validation."""
        allowed_roots = [tmp_path]

        # Create test file
        test_file = tmp_path / "test.txt"
        test_file.write_text("x" * 1024)

        # Validate path
        validated_path = validate_path_traversal(
            test_file,
            allowed_roots,
            must_exist=True
        )

        # Validate size
        sanitize_file_size(validated_path, max_size_mb=1)

        # Both should pass
        assert validated_path.exists()

    def test_attack_chain_prevention(self, tmp_path):
        """Test that attack chains are prevented."""
        allowed_roots = [tmp_path / "allowed"]

        # Attempt path traversal with command injection
        dangerous_path = "../../../etc/passwd; rm -rf /"

        with pytest.raises(SecurityError):
            target = tmp_path / "allowed" / dangerous_path
            validate_path_traversal(target, allowed_roots, must_exist=False)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
