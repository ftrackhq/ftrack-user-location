# :coding: utf-8
# :copyright: Copyright (c) 2018 ftrack

"""Sync report generation and attachment to ftrack Jobs."""

import json
import logging
import tempfile
import os
from datetime import datetime

logger = logging.getLogger(__name__)


def _format_duration(seconds):
    """Format duration in seconds to human-readable string."""
    if seconds < 60:
        return f"{seconds:.1f}s"
    elif seconds < 3600:
        minutes = seconds / 60
        return f"{minutes:.1f}m"
    else:
        hours = seconds / 3600
        return f"{hours:.1f}h"


def _format_size(bytes_size):
    """Format file size in bytes to human-readable string."""
    if bytes_size is None:
        return "unknown"

    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if bytes_size < 1024.0:
            return f"{bytes_size:.2f} {unit}"
        bytes_size /= 1024.0
    return f"{bytes_size:.2f} PB"


def generate_sync_report(
    source_name,
    destination_name,
    executor_username,
    requesting_user_id,
    components_synced,
    components_failed,
    components_skipped,
    duration,
    job_id
):
    """Generate a detailed sync report in Markdown format.

    Args:
        source_name: Name of source location
        destination_name: Name of destination location
        executor_username: Username of user executing the sync
        requesting_user_id: User ID who requested the sync
        components_synced: List of dicts with synced component details
        components_failed: List of dicts with failed component details
        components_skipped: List of dicts with skipped component details
        duration: Total sync duration in seconds
        job_id: ftrack Job ID

    Returns:
        str: Markdown-formatted report
    """
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    total = len(components_synced) + len(components_failed) + len(components_skipped)
    success_rate = (len(components_synced) / total * 100) if total > 0 else 0

    # Calculate total size if available
    total_size = sum(c.get('size', 0) for c in components_synced if c.get('size'))
    transfer_rate = (total_size / duration) if duration > 0 and total_size > 0 else 0

    report_lines = [
        "# Sync Report",
        "",
        f"**Generated**: {timestamp}  ",
        f"**Job ID**: `{job_id}`  ",
        f"**Executor**: {executor_username}  ",
        f"**Requesting User ID**: {requesting_user_id}  ",
        "",
        "---",
        "",
        "## Summary",
        "",
        f"**Source**: `{source_name}`  ",
        f"**Destination**: `{destination_name}`  ",
        f"**Duration**: {_format_duration(duration)}  ",
        f"**Success Rate**: {success_rate:.1f}%  ",
        "",
        f"- ✅ **Synced**: {len(components_synced)} components",
        f"- ⏭️ **Skipped**: {len(components_skipped)} components (already exist)",
        f"- ❌ **Failed**: {len(components_failed)} components",
        f"- 📊 **Total**: {total} components",
        "",
    ]

    if total_size > 0:
        report_lines.extend([
            f"**Data Transferred**: {_format_size(total_size)}  ",
            f"**Transfer Rate**: {_format_size(transfer_rate)}/s  ",
            "",
        ])

    report_lines.extend([
        "---",
        "",
    ])

    # Synced components section
    if components_synced:
        report_lines.extend([
            "## ✅ Successfully Synced",
            "",
            "| Component | Size | Asset Version |",
            "|-----------|------|---------------|",
        ])
        for comp in components_synced:
            name = comp.get('name', 'unknown')
            size = _format_size(comp.get('size')) if comp.get('size') else 'N/A'
            version = comp.get('version', 'N/A')
            report_lines.append(f"| `{name}` | {size} | {version} |")
        report_lines.extend(["", ""])

    # Skipped components section
    if components_skipped:
        report_lines.extend([
            "## ⏭️ Skipped (Already Exist)",
            "",
            "| Component | Reason | Asset Version |",
            "|-----------|--------|---------------|",
        ])
        for comp in components_skipped:
            name = comp.get('name', 'unknown')
            reason = comp.get('reason', 'Already exists at destination')
            version = comp.get('version', 'N/A')
            report_lines.append(f"| `{name}` | {reason} | {version} |")
        report_lines.extend(["", ""])

    # Failed components section
    if components_failed:
        report_lines.extend([
            "## ❌ Failed Components",
            "",
            "| Component | Error | Asset Version |",
            "|-----------|-------|---------------|",
        ])
        for comp in components_failed:
            name = comp.get('name', 'unknown')
            error = comp.get('error', 'Unknown error')
            # Truncate long error messages for table
            if len(error) > 60:
                error = error[:57] + "..."
            version = comp.get('version', 'N/A')
            report_lines.append(f"| `{name}` | {error} | {version} |")
        report_lines.extend(["", ""])

        # Detailed error section if there are failures
        report_lines.extend([
            "### Detailed Errors",
            "",
        ])
        for comp in components_failed:
            name = comp.get('name', 'unknown')
            error = comp.get('error', 'Unknown error')
            error_type = comp.get('error_type', 'Error')
            report_lines.extend([
                f"**{name}**:",
                f"- **Type**: `{error_type}`",
                f"- **Message**: {error}",
                "",
            ])

    # Performance metrics section
    report_lines.extend([
        "---",
        "",
        "## Performance Metrics",
        "",
        f"- **Total Duration**: {_format_duration(duration)}",
    ])

    if total > 0:
        components_per_sec = total / duration if duration > 0 else 0
        report_lines.append(f"- **Components/Second**: {components_per_sec:.2f}")

    if total_size > 0:
        report_lines.extend([
            f"- **Data Transferred**: {_format_size(total_size)}",
            f"- **Transfer Rate**: {_format_size(transfer_rate)}/s",
        ])

    report_lines.extend([
        "",
        "---",
        "",
        "*Report generated by ftrack User Location plugin v0.3.3*",
    ])

    return "\n".join(report_lines)


def attach_report_to_job(session, job_id, report_content, report_name="sync_report.md"):
    """Attach sync report as a component to the Job.

    Args:
        session: ftrack API session
        job_id: ftrack Job ID
        report_content: Report content as string (Markdown)
        report_name: Name for the report file (default: sync_report.md)

    Returns:
        str: Component ID if successful, None if failed
    """
    try:
        # Get the Job entity
        job = session.get('Job', job_id)

        # Create temporary file with report content
        with tempfile.NamedTemporaryFile(
            mode='w',
            suffix='.md',
            delete=False,
            encoding='utf-8'
        ) as temp_file:
            temp_file.write(report_content)
            temp_path = temp_file.name

        try:
            # Get ftrack.server location for storing the report
            server_location = session.query(
                'Location where name is "ftrack.server"'
            ).first()

            if not server_location:
                logger.error("ftrack.server location not found - cannot attach report")
                return None

            # Create component for the report
            component = session.create_component(
                temp_path,
                data={
                    'name': report_name
                },
                location=server_location
            )

            # Attach component to Job
            session.create('JobComponent', {
                'component_id': component['id'],
                'job_id': job_id
            })

            session.commit()

            logger.info(
                f"Sync report attached to Job [job_id={job_id}, "
                f"component_id={component['id']}, name={report_name}]"
            )

            return component['id']

        finally:
            # Clean up temp file
            try:
                os.unlink(temp_path)
            except Exception as e:
                logger.warning(f"Could not delete temp file {temp_path}: {e}")

    except Exception as error:
        logger.error(
            f"Failed to attach report to Job [job_id={job_id}, error={error}]"
        )
        import traceback
        logger.error(traceback.format_exc())
        return None


def create_and_attach_sync_report(
    session,
    job_id,
    source_name,
    destination_name,
    executor_username,
    requesting_user_id,
    components_synced,
    components_failed,
    components_skipped,
    duration
):
    """Generate sync report and attach it to the Job.

    Convenience function that combines report generation and attachment.

    Args:
        session: ftrack API session
        job_id: ftrack Job ID
        source_name: Name of source location
        destination_name: Name of destination location
        executor_username: Username of user executing the sync
        requesting_user_id: User ID who requested the sync
        components_synced: List of synced component dicts
        components_failed: List of failed component dicts
        components_skipped: List of skipped component dicts
        duration: Total sync duration in seconds

    Returns:
        str: Component ID if successful, None if failed
    """
    # Generate report content
    report_content = generate_sync_report(
        source_name=source_name,
        destination_name=destination_name,
        executor_username=executor_username,
        requesting_user_id=requesting_user_id,
        components_synced=components_synced,
        components_failed=components_failed,
        components_skipped=components_skipped,
        duration=duration,
        job_id=job_id
    )

    # Create filename with timestamp
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_name = f"sync_report_{source_name}_to_{destination_name}_{timestamp}.md"

    # Attach to Job
    return attach_report_to_job(
        session=session,
        job_id=job_id,
        report_content=report_content,
        report_name=report_name
    )
