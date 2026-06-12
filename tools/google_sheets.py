"""Google Sheets tools for Jarvis."""

from __future__ import annotations

from tools.google_auth import get_google_service


def get_sheets_service():
    return get_google_service("sheets", "v4")


def read_sheet(spreadsheet_id: str, range: str) -> str:
    """Read a cell range and return a plain-text table."""
    spreadsheet_id = (spreadsheet_id or "").strip()
    range = (range or "").strip()
    if not spreadsheet_id or not range:
        return "spreadsheet_id and range are required."
    service = get_sheets_service()
    result = (
        service.spreadsheets()
        .values()
        .get(spreadsheetId=spreadsheet_id, range=range)
        .execute()
    )
    values = result.get("values") or []
    if not values:
        return f"Range {range!r} is empty."
    lines = [f"Sheet data ({range}):"]
    for row in values:
        lines.append(" | ".join(str(cell) for cell in row))
    return "\n".join(lines)


def append_row(spreadsheet_id: str, sheet_name: str, values: list) -> str:
    """Append a row of values to a sheet."""
    spreadsheet_id = (spreadsheet_id or "").strip()
    sheet_name = (sheet_name or "Sheet1").strip()
    if not spreadsheet_id:
        return "spreadsheet_id is required."
    if isinstance(values, str):
        values = [v.strip() for v in values.split(",")]
    if not values:
        return "values must be a non-empty list."
    range_name = f"{sheet_name}!A1"
    service = get_sheets_service()
    body = {"values": [list(values)]}
    result = (
        service.spreadsheets()
        .values()
        .append(
            spreadsheetId=spreadsheet_id,
            range=range_name,
            valueInputOption="USER_ENTERED",
            insertDataOption="INSERT_ROWS",
            body=body,
        )
        .execute()
    )
    updated = result.get("updates", {}).get("updatedRows", 1)
    return f"Appended {updated} row(s) to {sheet_name!r}."


def update_cell(spreadsheet_id: str, cell: str, value: str) -> str:
    """Update a single cell (A1 notation, e.g. Sheet1!C5)."""
    spreadsheet_id = (spreadsheet_id or "").strip()
    cell = (cell or "").strip()
    if not spreadsheet_id or not cell:
        return "spreadsheet_id and cell are required."
    service = get_sheets_service()
    body = {"values": [[value]]}
    result = (
        service.spreadsheets()
        .values()
        .update(
            spreadsheetId=spreadsheet_id,
            range=cell,
            valueInputOption="USER_ENTERED",
            body=body,
        )
        .execute()
    )
    updated = result.get("updatedCells", 1)
    return f"Updated {updated} cell(s) at {cell!r} to {value!r}."
