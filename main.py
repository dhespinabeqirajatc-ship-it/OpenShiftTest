import decimal
import json
import os
import sys
import time
from enum import Enum
from typing import Any

import requests


CLIENT_ID = os.getenv("WORKIVA_CLIENT_ID", "").strip()
CLIENT_SECRET = os.getenv("WORKIVA_CLIENT_SECRET", "").strip()
CONTROL_SPREADSHEET_ID = os.getenv("WORKIVA_CONTROL_SPREADSHEET_ID", "").strip()
CONTROL_SHEET_ID = os.getenv("WORKIVA_CONTROL_SHEET_ID", "").strip()
CONTROL_CELL = os.getenv("WORKIVA_CONTROL_CELL", "B2").strip() or "B2"
API_VERSION = os.getenv("WORKIVA_API_VERSION", "2026-01-01").strip()
BASE_URL = os.getenv(
    "WORKIVA_BASE_URL",
    "https://api.eu.wdesk.com",
).strip().rstrip("/")
TARGET_NAME_TEXT = os.getenv(
    "WORKIVA_TARGET_NAME_TEXT", "zero"
).strip().casefold() or "zero"

AUTH_URL = f"{BASE_URL}/oauth2/token"
SS_API_URL = f"{BASE_URL}/spreadsheets"

required_settings = {
    "WORKIVA_CLIENT_ID": CLIENT_ID,
    "WORKIVA_CLIENT_SECRET": CLIENT_SECRET,
    "WORKIVA_CONTROL_SPREADSHEET_ID": CONTROL_SPREADSHEET_ID,
    "WORKIVA_CONTROL_SHEET_ID": CONTROL_SHEET_ID,
}
missing_settings = [k for k, v in required_settings.items() if not v]
if missing_settings:
    raise RuntimeError(
        "Missing required OpenShift environment variable(s): "
        + ", ".join(missing_settings)
    )


class NumberPrecision(Enum):
    BASIS_POINTS = 0.0001
    HUNDREDTHS = 0.01
    ONES = 1
    THOUSANDS = 1_000
    TEN_THOUSANDS = 10_000
    MILLIONS = 1_000_000
    HUNDRED_MILLIONS = 100_000_000
    BILLIONS = 1_000_000_000
    TRILLIONS = 1_000_000_000_000


class ApiAuth:
    def __init__(self):
        self.headers = {
            "X-Version": API_VERSION,
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        }

    def get_auth_token(self) -> str:
        print("Authenticating with Workiva...")
        try:
            response = requests.post(
                AUTH_URL,
                headers=self.headers,
                data={
                    "client_id": CLIENT_ID,
                    "client_secret": CLIENT_SECRET,
                    "grant_type": "client_credentials",
                },
                timeout=30,
            )
        except requests.RequestException as exc:
            raise RuntimeError(
                f"Could not connect to Workiva authentication API: {exc}"
            ) from exc

        print("Authentication status:", response.status_code)

        if not response.ok:
            raise RuntimeError(
                "Workiva authentication failed.\n\n"
                f"HTTP status: {response.status_code}\n"
                f"Response: {response.text}"
            )

        access_token = response.json().get("access_token")
        if not access_token:
            raise RuntimeError(
                "Authentication returned HTTP 200, but no access_token."
            )

        print("Authentication successful.")
        return access_token


class SpreadsheetApi:
    def __init__(self, access_token: str):
        self.access_token = access_token
        self.headers = self._headers(access_token)
        self.total_rows_hidden = 0

    @staticmethod
    def _headers(access_token: str) -> dict[str, str]:
        return {
            "X-Version": API_VERSION,
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def refresh_token(self) -> None:
        self.access_token = ApiAuth().get_auth_token()
        self.headers = self._headers(self.access_token)

    def request(self, method: str, url: str, **kwargs: Any) -> requests.Response:
        token_refreshed = False

        for _ in range(5):
            try:
                response = requests.request(
                    method=method,
                    url=url,
                    headers=self.headers,
                    timeout=60,
                    **kwargs,
                )
            except requests.RequestException as exc:
                raise RuntimeError(
                    f"Network error while talking to Workiva.\nURL: {url}\nError: {exc}"
                ) from exc

            if response.status_code == 401 and not token_refreshed:
                print("Bearer token expired or rejected; refreshing token...")
                token_refreshed = True
                self.refresh_token()
                continue

            if response.status_code == 429:
                retry_after = int(response.headers.get("Retry-After", "5"))
                print(f"Rate limit reached. Waiting {retry_after} seconds...")
                time.sleep(retry_after)
                continue

            if not response.ok:
                request_id = response.headers.get("X-Request-ID", "Not provided")
                raise RuntimeError(
                    "Workiva API returned an error.\n\n"
                    f"Method: {method}\n"
                    f"URL: {url}\n"
                    f"HTTP status: {response.status_code}\n"
                    f"X-Request-ID: {request_id}\n\n"
                    f"Response:\n{response.text}"
                )

            return response

        raise RuntimeError("Workiva request failed repeatedly.")

    def wait_for_operation(self, response: requests.Response) -> dict[str, Any] | None:
        if response.status_code != 202:
            return None

        operation_url = response.headers.get("Location")
        if not operation_url:
            try:
                operation_url = response.json().get("operationLocation")
            except ValueError:
                operation_url = None

        if not operation_url:
            raise RuntimeError(
                "Workiva returned HTTP 202, but no operation Location was supplied."
            )

        retry_after = int(response.headers.get("Retry-After", "2"))

        while True:
            time.sleep(retry_after)
            operation_response = self.request("GET", operation_url)
            operation = operation_response.json()
            status = str(operation.get("status", "")).lower()

            if status in ("completed", "succeeded", "success"):
                return operation

            if status in ("failed", "error", "cancelled", "canceled"):
                raise RuntimeError(
                    "Workiva asynchronous operation failed.\n\n"
                    + json.dumps(operation, indent=2)
                )

            retry_after = int(
                operation_response.headers.get("Retry-After", "2")
            )

    def get_target_spreadsheets(self) -> list[dict[str, Any]]:
        print(
            f"\nFinding spreadsheets containing {TARGET_NAME_TEXT!r} "
            "(case-insensitive)..."
        )

        url = SS_API_URL
        params = {"$maxpagesize": 1000, "$orderBy": "name asc"}
        matches: list[dict[str, Any]] = []

        while url:
            response = self.request("GET", url, params=params)
            result = response.json()

            for spreadsheet in result.get("data", []):
                name = str(spreadsheet.get("name", "")).strip()
                if TARGET_NAME_TEXT in name.casefold():
                    matches.append(spreadsheet)

            url = result.get("@nextLink")
            params = None

        print(f"Found {len(matches)} matching spreadsheet(s).")
        for spreadsheet in matches:
            print(
                f"  - {spreadsheet.get('name', '<unnamed>')} "
                f"[{spreadsheet.get('id', '<no id>')}]"
            )

        return matches

    def get_target_sheets(self, spreadsheet_id: str) -> list[dict[str, Any]]:
        print(
            f"\nFinding sheets containing {TARGET_NAME_TEXT!r} "
            "(case-insensitive)..."
        )

        url = f"{SS_API_URL}/{spreadsheet_id}/sheets"
        matches: list[dict[str, Any]] = []

        while url:
            response = self.request("GET", url)
            result = response.json()

            for sheet in result.get("data", []):
                name = str(sheet.get("name", "")).strip()
                if TARGET_NAME_TEXT in name.casefold():
                    matches.append(sheet)

            url = result.get("@nextLink")

        print(f"Found {len(matches)} matching sheet(s).")
        for sheet in matches:
            print(
                f"    - {sheet.get('name', '<unnamed>')} "
                f"[{sheet.get('id', '<no id>')}]"
            )

        return matches

    def get_cell_value(
        self,
        document_id: str,
        table_id: str,
        cell_range: str,
    ) -> Any:
        url = (
            f"{SS_API_URL}/{document_id}/sheets/"
            f"{table_id}/values/{cell_range}"
        )
        response = self.request(
            "GET",
            url,
            params={"$valuestyle": "calculated"},
        )

        data = response.json().get("data", [])
        if not data:
            return None

        values = data[0].get("values", [])
        if not values or not values[0]:
            return None

        return values[0][0]

    def set_cell_value(
        self,
        document_id: str,
        table_id: str,
        cell_range: str,
        value: Any,
    ) -> None:
        url = (
            f"{SS_API_URL}/{document_id}/sheets/"
            f"{table_id}/values/{cell_range}"
        )
        response = self.request(
            "PUT",
            url,
            json={"values": [[value]]},
        )
        self.wait_for_operation(response)

    def get_table_data(
        self,
        document_id: str,
        table_id: str,
    ) -> list[list[dict[str, Any]]]:
        url = (
            f"{SS_API_URL}/{document_id}/sheets/"
            f"{table_id}/sheetdata"
        )
        params = {
            "$maxcellsperpage": 50000,
            "$fields": (
                "cells.calculatedValue,"
                "cells.formats.valueFormat,"
                "cells.effectiveFormats.valueFormat"
            ),
        }

        rows: list[list[dict[str, Any]]] = []
        first_request = True

        while url:
            response = self.request(
                "GET",
                url,
                params=params if first_request else None,
            )
            first_request = False
            result = response.json()
            rows.extend(result.get("data", {}).get("cells", []))
            url = result.get("@nextLink")

        return rows

    def hide_table_rows(
        self,
        document_id: str,
        table_id: str,
        row_indices: list[int],
    ) -> None:
        if not row_indices:
            return

        row_indices = sorted(set(row_indices))
        self.total_rows_hidden += len(row_indices)

        intervals = []
        start_index = row_indices[0]
        end_index = row_indices[0]

        for index in row_indices[1:]:
            if index > end_index + 1:
                intervals.append({"start": start_index, "end": end_index})
                start_index = index
            end_index = index

        intervals.append({"start": start_index, "end": end_index})

        url = f"{SS_API_URL}/{document_id}/sheets/{table_id}/update"
        response = self.request(
            "POST",
            url,
            json={"hideRows": {"intervals": intervals}},
        )
        self.wait_for_operation(response)

    def unhide_table_rows(
        self,
        document_id: str,
        table_id: str,
    ) -> None:
        url = f"{SS_API_URL}/{document_id}/sheets/{table_id}/update"
        response = self.request(
            "POST",
            url,
            json={"unhideRows": {"intervals": [{}]}},
        )
        self.wait_for_operation(response)

    def get_rows_as_displayed(
        self,
        document_id: str,
        table_id: str,
    ) -> list[list[Any]]:
        rows_as_displayed = []

        for row in self.get_table_data(document_id, table_id):
            displayed_row = []

            for cell in row:
                calculated_value = cell.get("calculatedValue")

                if not isinstance(calculated_value, decimal.Decimal):
                    try:
                        calculated_value = decimal.Decimal(
                            str(calculated_value)
                        )
                    except (
                        decimal.InvalidOperation,
                        ValueError,
                        TypeError,
                    ):
                        pass

                displayed_value = calculated_value

                if isinstance(displayed_value, decimal.Decimal):
                    value_format = cell.get("formats", {}).get(
                        "valueFormat", {}
                    )

                    if not value_format:
                        value_format = cell.get(
                            "effectiveFormats", {}
                        ).get("valueFormat", {})

                    shown_in = value_format.get("shownIn")
                    if shown_in:
                        precision_name = (
                            str(shown_in)
                            .replace(" ", "_")
                            .upper()
                        )
                        if precision_name in NumberPrecision.__members__:
                            scale = NumberPrecision[precision_name].value
                            displayed_value /= decimal.Decimal(str(scale))

                    precision = value_format.get("precision")
                    if precision and not precision.get("auto", True):
                        precision_value = precision.get("value", 0)
                        displayed_value = displayed_value.quantize(
                            decimal.Decimal(10) ** precision_value,
                            rounding=decimal.ROUND_HALF_UP,
                        )

                displayed_row.append(displayed_value)

            rows_as_displayed.append(displayed_row)

        return rows_as_displayed

    @staticmethod
    def section_rows_to_hide(
        start_row: int,
        stop_row: int,
        zero_rows: list[int],
        has_numeric_data: bool,
        has_non_zero_numeric_data: bool,
    ) -> list[int]:
        if has_non_zero_numeric_data:
            return zero_rows

        if has_numeric_data:
            return list(range(start_row, stop_row + 1))

        return []

    def find_rows_to_hide(
        self,
        rows: list[list[Any]],
    ) -> list[int]:
        rows_to_hide = []
        title_row = None
        zero_rows = []
        has_numeric_data = False
        has_non_zero_numeric_data = False

        for row_index, row in enumerate(rows):
            is_spacer_row = True
            has_numbers = False
            all_zeroes = True

            for cell in row:
                if cell not in (None, ""):
                    is_spacer_row = False

                if isinstance(cell, decimal.Decimal):
                    has_numbers = True
                    if cell != 0:
                        all_zeroes = False
                        break

            if is_spacer_row:
                if title_row is not None:
                    rows_to_hide.extend(
                        self.section_rows_to_hide(
                            title_row,
                            row_index,
                            zero_rows,
                            has_numeric_data,
                            has_non_zero_numeric_data,
                        )
                    )
                    title_row = None
                    zero_rows = []
                    has_numeric_data = False
                    has_non_zero_numeric_data = False

            else:
                if title_row is None:
                    title_row = row_index

                if has_numbers:
                    has_numeric_data = True
                    if all_zeroes:
                        zero_rows.append(row_index)
                    else:
                        has_non_zero_numeric_data = True

        if title_row is not None:
            rows_to_hide.extend(
                self.section_rows_to_hide(
                    title_row,
                    len(rows) - 1,
                    zero_rows,
                    has_numeric_data,
                    has_non_zero_numeric_data,
                )
            )

        return sorted(set(rows_to_hide))

    def process_target_sheets(self, spreadsheet_id: str) -> int:
        target_sheets = self.get_target_sheets(spreadsheet_id)

        if not target_sheets:
            print("No matching sheets in this spreadsheet. Skipping it.")
            return 0

        self.total_rows_hidden = 0

        for number, sheet in enumerate(target_sheets, start=1):
            sheet_id = sheet.get("id")
            sheet_name = sheet.get("name", "<unnamed>")

            if not sheet_id:
                print(f"Skipping {sheet_name!r}: no sheet ID returned.")
                continue

            print("\n-----------------------------------------")
            print(f"Processing target sheet {number}/{len(target_sheets)}")
            print(f"Sheet name: {sheet_name}")
            print(f"Sheet ID: {sheet_id}")
            print("-----------------------------------------")

            # Only matching sheets are ever unhidden or modified.
            print("STEP 1: Unhide existing hidden rows in this target sheet")
            self.unhide_table_rows(spreadsheet_id, sheet_id)

            print("STEP 2: Find and hide zero rows in this target sheet")
            rows = self.get_rows_as_displayed(spreadsheet_id, sheet_id)
            rows_to_hide = self.find_rows_to_hide(rows)

            print(f"Rows examined: {len(rows)}")
            print(f"Rows to hide: {len(rows_to_hide)}")

            if rows_to_hide:
                self.hide_table_rows(
                    spreadsheet_id,
                    sheet_id,
                    rows_to_hide,
                )
                print("Rows hidden successfully.")
            else:
                print("Nothing to hide.")

        print(
            "TOTAL ROWS HIDDEN IN MATCHING SHEETS OF THIS SPREADSHEET: "
            f"{self.total_rows_hidden}"
        )
        return self.total_rows_hidden


def normalize_boolean(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value

    if isinstance(value, str):
        normalized = value.strip().upper()
        if normalized == "TRUE":
            return True
        if normalized == "FALSE":
            return False

    return None


def suppress_zeros_for_spreadsheets(
    spreadsheet_api: SpreadsheetApi,
    spreadsheets: list[dict[str, Any]],
) -> None:
    total = len(spreadsheets)

    for number, spreadsheet in enumerate(spreadsheets, start=1):
        spreadsheet_id = spreadsheet.get("id")
        spreadsheet_name = spreadsheet.get("name", "<unnamed>")

        if not spreadsheet_id:
            print(f"Skipping {spreadsheet_name!r}: no spreadsheet ID returned.")
            continue

        print("\n\n###########################################")
        print(f"SPREADSHEET {number}/{total}")
        print(f"Spreadsheet name: {spreadsheet_name}")
        print(f"Spreadsheet ID: {spreadsheet_id}")
        print("###########################################")

        # Only target sheets within this target spreadsheet are processed.
        spreadsheet_api.process_target_sheets(spreadsheet_id)

        print(f"Spreadsheet {number}/{total} completed successfully.")


def main() -> None:
    print("===========================================")
    print("WORKIVA ZERO ROW HIDER - AUTO DISCOVERY")
    print(f"API version: {API_VERSION}")
    print(f"Python platform: {sys.platform}")
    print(f"Requests version: {requests.__version__}")
    print(
        f"Target name text: {TARGET_NAME_TEXT!r} "
        "(case-insensitive substring match)"
    )
    print("===========================================")

    # 1. POST /oauth2/token to generate a fresh bearer token.
    auth_token = ApiAuth().get_auth_token()

    # 2. Use the bearer token for Workiva API calls.
    spreadsheet_api = SpreadsheetApi(auth_token)

    # 3. Read the TRUE/FALSE control cell.
    print("\nChecking zero-suppression control cell...")
    print(f"Control spreadsheet: {CONTROL_SPREADSHEET_ID}")
    print(f"Control sheet: {CONTROL_SHEET_ID}")
    print(f"Control cell: {CONTROL_CELL}")

    raw_control_value = spreadsheet_api.get_cell_value(
        CONTROL_SPREADSHEET_ID,
        CONTROL_SHEET_ID,
        CONTROL_CELL,
    )
    control_value = normalize_boolean(raw_control_value)

    print(f"Control value returned by Workiva: {raw_control_value!r}")

    if control_value is True:
        print("Control cell is TRUE. Nothing to do.")
        return

    if control_value is not False:
        raise RuntimeError(
            "The control cell must contain TRUE or FALSE.\n"
            f"Current value: {raw_control_value!r}"
        )

    print("\nCONTROL CELL IS FALSE - STARTING RUN")

    # 4. GET all visible spreadsheets and keep only names containing "zero"
    #    case-insensitively.
    target_spreadsheets = spreadsheet_api.get_target_spreadsheets()

    if not target_spreadsheets:
        raise RuntimeError(
            f"No spreadsheets were found whose name contains "
            f"{TARGET_NAME_TEXT!r}. "
            "The control cell will remain FALSE."
        )

    # 5. For every matching spreadsheet, GET its sheets and only process
    #    sheets whose names also contain "zero" case-insensitively.
    suppress_zeros_for_spreadsheets(
        spreadsheet_api,
        target_spreadsheets,
    )

    # 6. Only after every target succeeds, reset the control cell to TRUE.
    print("\nALL MATCHING SPREADSHEETS COMPLETED SUCCESSFULLY")
    print("Resetting control cell to TRUE...")

    spreadsheet_api.set_cell_value(
        CONTROL_SPREADSHEET_ID,
        CONTROL_SHEET_ID,
        CONTROL_CELL,
        True,
    )

    print("Control cell reset to TRUE successfully.")
    print("Done.")


if __name__ == "__main__":
    main()
