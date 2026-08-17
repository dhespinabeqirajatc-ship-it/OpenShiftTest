import decimal
import json
import os
import sys
import time
from enum import Enum
from typing import Any

import requests


# ============================================================
# OPENSHIFT CONFIGURATION
# ============================================================

CLIENT_ID = os.getenv("WORKIVA_CLIENT_ID", "").strip()
CLIENT_SECRET = os.getenv("WORKIVA_CLIENT_SECRET", "").strip()

CONTROL_SPREADSHEET_ID = os.getenv(
    "WORKIVA_CONTROL_SPREADSHEET_ID", ""
).strip()

CONTROL_SHEET_ID = os.getenv(
    "WORKIVA_CONTROL_SHEET_ID", ""
).strip()

CONTROL_CELL = os.getenv(
    "WORKIVA_CONTROL_CELL", "B2"
).strip() or "B2"

API_VERSION = os.getenv(
    "WORKIVA_API_VERSION", "2026-01-01"
).strip()

BASE_URL = os.getenv(
    "WORKIVA_BASE_URL",
    "https://api.eu.wdesk.com",
).strip().rstrip("/")

# Exact, case-insensitive target name.
# "Zero", "zero", " ZERO " all match.
# "Zero Adjustments" does NOT match.
TARGET_NAME = os.getenv(
    "WORKIVA_TARGET_NAME", "zero"
).strip().casefold() or "zero"

AUTH_URL = f"{BASE_URL}/oauth2/token"
SS_API_URL = f"{BASE_URL}/spreadsheets"


required_settings = {
    "WORKIVA_CLIENT_ID": CLIENT_ID,
    "WORKIVA_CLIENT_SECRET": CLIENT_SECRET,
    "WORKIVA_CONTROL_SPREADSHEET_ID": CONTROL_SPREADSHEET_ID,
    "WORKIVA_CONTROL_SHEET_ID": CONTROL_SHEET_ID,
}

missing_settings = [
    key for key, value in required_settings.items()
    if not value
]

if missing_settings:
    raise RuntimeError(
        "Missing required OpenShift environment variable(s): "
        + ", ".join(missing_settings)
    )


# ============================================================
# AUTHENTICATION
# ============================================================

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
                "Authentication returned HTTP 200 but no access_token."
            )

        print("Authentication successful.")
        return access_token


# ============================================================
# WORKIVA API CLIENT
# ============================================================

class SpreadsheetApi:
    def __init__(self, access_token: str):
        self.access_token = access_token
        self.headers = self._make_headers(access_token)
        self.total_rows_hidden = 0

    @staticmethod
    def _make_headers(access_token: str) -> dict[str, str]:
        return {
            "X-Version": API_VERSION,
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def refresh_token(self) -> None:
        print("Refreshing Workiva access token...")
        self.access_token = ApiAuth().get_auth_token()
        self.headers = self._make_headers(self.access_token)

    def request(
        self,
        method: str,
        url: str,
        **kwargs: Any,
    ) -> requests.Response:
        """
        Workiva request helper:
        - retries rate limits
        - refreshes an expired token once on HTTP 401
        - reports Workiva request IDs for troubleshooting
        """

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
                    "Network error while talking to Workiva.\n"
                    f"URL: {url}\n"
                    f"Error: {exc}"
                ) from exc

            if response.status_code == 401 and not token_refreshed:
                token_refreshed = True
                self.refresh_token()
                continue

            if response.status_code == 429:
                retry_after = int(
                    response.headers.get("Retry-After", "5")
                )
                print(
                    f"Rate limit reached. Waiting {retry_after} seconds..."
                )
                time.sleep(retry_after)
                continue

            if not response.ok:
                request_id = response.headers.get(
                    "X-Request-ID",
                    "Not provided",
                )
                raise RuntimeError(
                    "Workiva API returned an error.\n\n"
                    f"Method: {method}\n"
                    f"URL: {url}\n"
                    f"HTTP status: {response.status_code}\n"
                    f"X-Request-ID: {request_id}\n\n"
                    f"Response:\n{response.text}"
                )

            return response

        raise RuntimeError(
            "Workiva request failed repeatedly."
        )

    def wait_for_operation(
        self,
        response: requests.Response,
    ) -> dict[str, Any] | None:
        if response.status_code != 202:
            return None

        operation_url = response.headers.get("Location")

        if not operation_url:
            try:
                operation_url = response.json().get(
                    "operationLocation"
                )
            except ValueError:
                operation_url = None

        if not operation_url:
            raise RuntimeError(
                "Workiva returned HTTP 202 but no operation "
                "Location was supplied."
            )

        retry_after = int(
            response.headers.get("Retry-After", "2")
        )

        while True:
            time.sleep(retry_after)

            operation_response = self.request(
                "GET",
                operation_url,
            )

            operation = operation_response.json()
            status = str(
                operation.get("status", "")
            ).lower()

            if status in (
                "completed",
                "succeeded",
                "success",
            ):
                return operation

            if status in (
                "failed",
                "error",
                "cancelled",
                "canceled",
            ):
                raise RuntimeError(
                    "Workiva asynchronous operation failed.\n\n"
                    + json.dumps(operation, indent=2)
                )

            retry_after = int(
                operation_response.headers.get(
                    "Retry-After", "2"
                )
            )

    # ========================================================
    # 1. GET ALL SPREADSHEETS: NAME + ID
    # ========================================================

    def get_all_spreadsheets(
        self,
    ) -> list[dict[str, Any]]:
        """
        Retrieve every spreadsheet visible to this OAuth client.
        Follows @nextLink until all pages are collected.
        """

        print("\nRetrieving all Workiva spreadsheets...")

        url = SS_API_URL
        params = {
            "$maxpagesize": 1000,
            "$orderBy": "name asc",
        }

        spreadsheets: list[dict[str, Any]] = []

        while url:
            response = self.request(
                "GET",
                url,
                params=params,
            )

            result = response.json()

            for spreadsheet in result.get("data", []):
                spreadsheet_id = spreadsheet.get("id")
                spreadsheet_name = str(
                    spreadsheet.get("name", "")
                ).strip()

                if spreadsheet_id:
                    spreadsheets.append(
                        {
                            "id": spreadsheet_id,
                            "name": spreadsheet_name,
                        }
                    )

            url = result.get("@nextLink")
            params = None

        print(
            f"Retrieved {len(spreadsheets)} spreadsheet(s)."
        )

        for spreadsheet in spreadsheets:
            print(
                f"  Spreadsheet: {spreadsheet['name']} "
                f"| ID: {spreadsheet['id']}"
            )

        return spreadsheets

    @staticmethod
    def exact_name_matches(
        name: str,
    ) -> bool:
        return str(name).strip().casefold() == TARGET_NAME

    def filter_zero_spreadsheets(
        self,
        spreadsheets: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        matches = [
            spreadsheet
            for spreadsheet in spreadsheets
            if self.exact_name_matches(
                spreadsheet.get("name", "")
            )
        ]

        print(
            f"\nSpreadsheet exact-name filter {TARGET_NAME!r}: "
            f"{len(matches)} match(es)."
        )

        for spreadsheet in matches:
            print(
                f"  MATCH: {spreadsheet['name']} "
                f"| ID: {spreadsheet['id']}"
            )

        return matches

    # ========================================================
    # 2. GET ALL SHEETS: NAME + ID, THEN FILTER
    # ========================================================

    @staticmethod
    def _flatten_sheets(
        sheets: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """
        Workiva sheets can be hierarchical. Flatten top-level and
        child sheets so every returned sheet name/ID can be evaluated.
        """

        flattened: list[dict[str, Any]] = []

        def visit(sheet: dict[str, Any]) -> None:
            flattened.append(sheet)

            children = sheet.get("children") or []

            for child in children:
                if isinstance(child, dict):
                    visit(child)

        for sheet in sheets:
            if isinstance(sheet, dict):
                visit(sheet)

        return flattened

    def get_all_sheets(
        self,
        spreadsheet_id: str,
    ) -> list[dict[str, Any]]:
        print(
            f"\nRetrieving all sheets for spreadsheet "
            f"{spreadsheet_id}..."
        )

        url = (
            f"{SS_API_URL}/"
            f"{spreadsheet_id}/sheets"
        )

        raw_sheets: list[dict[str, Any]] = []

        while url:
            response = self.request(
                "GET",
                url,
            )

            result = response.json()

            raw_sheets.extend(
                result.get("data", [])
            )

            url = result.get("@nextLink")

        flattened = self._flatten_sheets(
            raw_sheets
        )

        # De-duplicate in case child sheets are also returned
        # independently by the endpoint.
        seen_ids: set[str] = set()
        sheets: list[dict[str, Any]] = []

        for sheet in flattened:
            sheet_id = sheet.get("id")

            if not sheet_id or sheet_id in seen_ids:
                continue

            seen_ids.add(sheet_id)

            sheets.append(
                {
                    "id": sheet_id,
                    "name": str(
                        sheet.get("name", "")
                    ).strip(),
                }
            )

        print(
            f"Retrieved {len(sheets)} sheet(s)."
        )

        for sheet in sheets:
            print(
                f"    Sheet: {sheet['name']} "
                f"| ID: {sheet['id']}"
            )

        return sheets

    def filter_zero_sheets(
        self,
        sheets: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        matches = [
            sheet
            for sheet in sheets
            if self.exact_name_matches(
                sheet.get("name", "")
            )
        ]

        print(
            f"Sheet exact-name filter {TARGET_NAME!r}: "
            f"{len(matches)} match(es)."
        )

        for sheet in matches:
            print(
                f"    MATCH: {sheet['name']} "
                f"| ID: {sheet['id']}"
            )

        return matches

    # ========================================================
    # CONTROL CELL
    # ========================================================

    def get_cell_value(
        self,
        spreadsheet_id: str,
        sheet_id: str,
        cell_range: str,
    ) -> Any:
        url = (
            f"{SS_API_URL}/"
            f"{spreadsheet_id}/sheets/"
            f"{sheet_id}/values/"
            f"{cell_range}"
        )

        response = self.request(
            "GET",
            url,
            params={
                "$valuestyle": "calculated",
            },
        )

        data = response.json().get(
            "data", []
        )

        if not data:
            return None

        values = data[0].get(
            "values", []
        )

        if not values or not values[0]:
            return None

        return values[0][0]

    def set_cell_value(
        self,
        spreadsheet_id: str,
        sheet_id: str,
        cell_range: str,
        value: Any,
    ) -> None:
        url = (
            f"{SS_API_URL}/"
            f"{spreadsheet_id}/sheets/"
            f"{sheet_id}/values/"
            f"{cell_range}"
        )

        response = self.request(
            "PUT",
            url,
            json={
                "values": [
                    [value]
                ]
            },
        )

        self.wait_for_operation(
            response
        )

    # ========================================================
    # 3. READ TARGET SHEET
    # ========================================================

    def get_sheet_rows(
        self,
        spreadsheet_id: str,
        sheet_id: str,
    ) -> list[list[Any]]:
        """
        Read calculated values from the entire sheet.
        """

        url = (
            f"{SS_API_URL}/"
            f"{spreadsheet_id}/sheets/"
            f"{sheet_id}/sheetdata"
        )

        params = {
            "$maxcellsperpage": 50000,
            "$fields": "cells.calculatedValue",
        }

        first_request = True
        rows: list[list[Any]] = []

        while url:
            response = self.request(
                "GET",
                url,
                params=(
                    params
                    if first_request
                    else None
                ),
            )

            first_request = False

            result = response.json()

            cells = (
                result
                .get("data", {})
                .get("cells", [])
            )

            for row in cells:
                rows.append(
                    [
                        cell.get("calculatedValue")
                        if isinstance(cell, dict)
                        else None
                        for cell in row
                    ]
                )

            url = result.get("@nextLink")

        return rows

    # ========================================================
    # 4. FIND EVERY ROW THAT CONTAINS NUMERIC ZERO
    # ========================================================

    @staticmethod
    def is_numeric_zero(
        value: Any,
    ) -> bool:
        """
        Treat numeric 0 values as zero.

        Handles Workiva JSON numbers and numeric strings such as:
        0, 0.0, "0", "0.00".

        Blank cells, booleans, and arbitrary text do not count.
        """

        if value is None or value == "":
            return False

        if isinstance(value, bool):
            return False

        try:
            return decimal.Decimal(
                str(value).strip()
            ) == 0
        except (
            decimal.InvalidOperation,
            ValueError,
            TypeError,
        ):
            return False

    def find_rows_containing_zero(
        self,
        rows: list[list[Any]],
    ) -> list[int]:
        """
        Hide a row if ANY cell in that row is numeric zero.
        """

        matching_rows: list[int] = []

        for row_index, row in enumerate(
            rows
        ):
            if any(
                self.is_numeric_zero(cell)
                for cell in row
            ):
                matching_rows.append(
                    row_index
                )

        return matching_rows

    # ========================================================
    # 5. HIDE MATCHING ROWS
    # ========================================================

    def hide_rows(
        self,
        spreadsheet_id: str,
        sheet_id: str,
        row_indices: list[int],
    ) -> None:
        if not row_indices:
            print(
                "No rows containing numeric zero were found."
            )
            return

        row_indices = sorted(
            set(row_indices)
        )

        intervals = []

        start_index = row_indices[0]
        end_index = row_indices[0]

        for index in row_indices[1:]:
            if index == end_index + 1:
                end_index = index
                continue

            intervals.append(
                {
                    "start": start_index,
                    "end": end_index,
                }
            )

            start_index = index
            end_index = index

        intervals.append(
            {
                "start": start_index,
                "end": end_index,
            }
        )

        url = (
            f"{SS_API_URL}/"
            f"{spreadsheet_id}/sheets/"
            f"{sheet_id}/update"
        )

        response = self.request(
            "POST",
            url,
            json={
                "hideRows": {
                    "intervals": intervals
                }
            },
        )

        self.wait_for_operation(
            response
        )

        self.total_rows_hidden += len(
            row_indices
        )

        print(
            f"Hidden {len(row_indices)} row(s) "
            "containing numeric zero."
        )

    # ========================================================
    # COMPLETE DISCOVERY + FILTER + HIDE FLOW
    # ========================================================

    def process_zero_targets(
        self,
    ) -> None:
        # A. Get names and IDs of every spreadsheet.
        all_spreadsheets = (
            self.get_all_spreadsheets()
        )

        # B. Exact case-insensitive spreadsheet name = "zero".
        zero_spreadsheets = (
            self.filter_zero_spreadsheets(
                all_spreadsheets
            )
        )

        if not zero_spreadsheets:
            raise RuntimeError(
                "No spreadsheet named 'Zero' "
                "(case-insensitive) was found."
            )

        for spreadsheet_number, spreadsheet in enumerate(
            zero_spreadsheets,
            start=1,
        ):
            spreadsheet_id = spreadsheet["id"]
            spreadsheet_name = spreadsheet["name"]

            print("\n")
            print("===========================================")
            print(
                f"TARGET SPREADSHEET "
                f"{spreadsheet_number}/"
                f"{len(zero_spreadsheets)}"
            )
            print(
                f"Name: {spreadsheet_name}"
            )
            print(
                f"ID: {spreadsheet_id}"
            )
            print("===========================================")

            # C. Get names and IDs of every sheet in this spreadsheet.
            all_sheets = self.get_all_sheets(
                spreadsheet_id
            )

            # D. Exact case-insensitive sheet name = "zero".
            zero_sheets = self.filter_zero_sheets(
                all_sheets
            )

            if not zero_sheets:
                print(
                    "No sheet named 'Zero' "
                    "(case-insensitive) in this spreadsheet. "
                    "Skipping."
                )
                continue

            for sheet_number, sheet in enumerate(
                zero_sheets,
                start=1,
            ):
                sheet_id = sheet["id"]
                sheet_name = sheet["name"]

                print("\n-------------------------------------------")
                print(
                    f"TARGET SHEET "
                    f"{sheet_number}/"
                    f"{len(zero_sheets)}"
                )
                print(
                    f"Name: {sheet_name}"
                )
                print(
                    f"ID: {sheet_id}"
                )
                print("-------------------------------------------")

                rows = self.get_sheet_rows(
                    spreadsheet_id,
                    sheet_id,
                )

                print(
                    f"Rows read: {len(rows)}"
                )

                zero_rows = (
                    self.find_rows_containing_zero(
                        rows
                    )
                )

                print(
                    f"Rows containing numeric zero: "
                    f"{len(zero_rows)}"
                )

                self.hide_rows(
                    spreadsheet_id,
                    sheet_id,
                    zero_rows,
                )

        print("\n===========================================")
        print(
            f"TOTAL ROWS HIDDEN: "
            f"{self.total_rows_hidden}"
        )
        print("===========================================")


# ============================================================
# CONTROL FLAG
# ============================================================

def normalize_boolean(
    value: Any,
) -> bool | None:
    if isinstance(value, bool):
        return value

    if isinstance(value, str):
        normalized = value.strip().upper()

        if normalized == "TRUE":
            return True

        if normalized == "FALSE":
            return False

    return None


# ============================================================
# MAIN
# ============================================================

def main() -> None:
    print("===========================================")
    print("WORKIVA ZERO ROW HIDER")
    print("DISCOVERY -> FILTER -> HIDE")
    print(f"API version: {API_VERSION}")
    print(f"Python platform: {sys.platform}")
    print(f"Requests version: {requests.__version__}")
    print(
        "Spreadsheet/sheet target name: "
        "'Zero' (exact, case-insensitive)"
    )
    print(
        "Row rule: hide row when ANY cell "
        "contains numeric zero"
    )
    print("===========================================")

    # 1. Generate a fresh bearer token.
    token = ApiAuth().get_auth_token()

    # 2. Create API client.
    api = SpreadsheetApi(token)

    # 3. Keep the existing TRUE/FALSE control mechanism.
    print(
        "\nChecking zero-suppression control cell..."
    )

    raw_control_value = api.get_cell_value(
        CONTROL_SPREADSHEET_ID,
        CONTROL_SHEET_ID,
        CONTROL_CELL,
    )

    control_value = normalize_boolean(
        raw_control_value
    )

    print(
        f"Control value: "
        f"{raw_control_value!r}"
    )

    if control_value is True:
        print(
            "Control cell is TRUE. "
            "No run requested."
        )
        return

    if control_value is not False:
        raise RuntimeError(
            "The control cell must contain TRUE or FALSE.\n"
            f"Current value: {raw_control_value!r}"
        )

    # 4. Discover/filter/process.
    api.process_zero_targets()

    # 5. Only reset TRUE after the entire run succeeds.
    print(
        "\nAll target processing completed successfully."
    )
    print(
        "Resetting control cell to TRUE..."
    )

    api.set_cell_value(
        CONTROL_SPREADSHEET_ID,
        CONTROL_SHEET_ID,
        CONTROL_CELL,
        True,
    )

    print(
        "Control cell reset to TRUE."
    )
    print("Done.")


if __name__ == "__main__":
    main()
