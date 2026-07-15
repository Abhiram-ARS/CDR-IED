import base64
import csv
import io
import os
import sqlite3
import subprocess
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
import matplotlib

import webview 
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

"""
CDR-IED: Call Detail Record Interpretation and Examination Dashboard
Backend: Handles CSV parsing, validation, and search logic
Frontend: fend.html (JavaScript) - Handles UI, rendering, and user interactions
Communication: PyWebView API exposing CDRBackend methods to JavaScript
"""

class Functions:
    def __init__(self):
        self.rows_data = []
        self.required_cols = ['A-Party','B-Party','Call Type','Start Date','Start Time','Duration','IMEI','IMSI','Cell ID','Call Status']
        self.db_path = None
        self.temp_data_dir = Path(__file__).resolve().parent / 'Temp_Data'
        self.export_data_dir = Path(__file__).resolve().parent / 'Export_Files'
        self._ensure_temp_data_dir()
        self.statistics = Statistics(self.temp_data_dir)

    def _ensure_temp_data_dir(self):
        """Create the shared folder for temporary databases and PNG files."""
        self.temp_data_dir.mkdir(parents=True, exist_ok=True)

    def _close_database(self):
        """Close and remove the temporary SQLite database if it exists."""
        if self.db_path and os.path.exists(self.db_path):
            try:
                os.remove(self.db_path)
            except OSError:
                pass
        self.db_path = None

    def _open_database(self):
        """Open a SQLite connection to the current temporary database."""
        if not self.db_path:
            return None

        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        connection.create_function('DURATION_SECONDS', 1, self._duration_seconds)
        connection.create_function('DATE_KEY', 1, self._date_key)
        return connection

    @staticmethod
    def _duration_seconds(value):
        """Convert numeric or clock-style duration text to seconds for SQL comparisons."""
        text = (value or '').strip()
        if not text:
            return None

        try:
            return float(text)
        except ValueError:
            pass

        parts = text.split(':')
        if len(parts) not in {2, 3}:
            return None

        try:
            numbers = [float(part.strip()) for part in parts]
        except ValueError:
            return None

        if len(numbers) == 2:
            minutes, seconds = numbers
            return minutes * 60 + seconds

        hours, minutes, seconds = numbers
        return hours * 3600 + minutes * 60 + seconds

    @staticmethod
    def _date_key(value):
        """Convert supported date text to ISO format for SQL comparisons."""
        parsed = Functions._parse_date_value(value)
        return parsed.strftime('%Y-%m-%d') if parsed else None

    @staticmethod
    def _parse_date_value(value):
        text = (value or '').strip()
        if not text:
            return None

        for date_format in (
            '%Y-%m-%d', '%d-%m-%Y', '%d/%m/%Y', '%m/%d/%Y',
            '%Y/%m/%d', '%d-%b-%Y', '%d-%B-%Y',
        ):
            try:
                return datetime.strptime(text, date_format)
            except ValueError:
                continue
        return None

    def _create_database(self):
        """Create a visible SQLite database file for the loaded records."""
        self._close_database()
        self._ensure_temp_data_dir()
        self.db_path = str(self.temp_data_dir / 'cdr_temp.db')

        connection = self._open_database()
        columns_sql = ', '.join('"{}" TEXT'.format(col) for col in self.required_cols)
        connection.execute('DROP TABLE IF EXISTS cdr_records')
        connection.execute(
            'CREATE TABLE cdr_records (si INTEGER PRIMARY KEY AUTOINCREMENT, {})'.format(columns_sql)
        )
        connection.commit()
        connection.close()

    def _store_rows_in_database(self, data_rows):
        """Persist the parsed rows in the temporary SQLite database."""
        self._create_database()
        connection = self._open_database()
        if connection is None:
            return

        if not data_rows:
            connection.commit()
            connection.close()
            return

        column_sql = ', '.join('"{}"'.format(col) for col in self.required_cols)
        placeholder_sql = ', '.join('?' for _ in self.required_cols)
        insert_sql = 'INSERT INTO cdr_records ({}) VALUES ({})'.format(column_sql, placeholder_sql)
        values = [[row.get(col, '') for col in self.required_cols] for row in data_rows]
        connection.executemany(insert_sql, values)
        connection.commit()
        connection.close()

    def _fetch_records(self, where_clause='', params=()):
        """Fetch records from the temporary SQLite database."""
        connection = self._open_database()
        if connection is None:
            return []

        column_sql = ', '.join('"{}"'.format(col) for col in self.required_cols)
        sql = 'SELECT si, {} FROM cdr_records'.format(column_sql)
        if where_clause:
            sql = '{} WHERE {}'.format(sql, where_clause)
        sql = '{} ORDER BY si'.format(sql)

        cursor = connection.execute(sql, params)
        rows = [dict(row) for row in cursor.fetchall()]
        connection.close()
        return rows

    def _count_records(self, where_clause='', params=()):
        """Count records in the temporary SQLite database."""
        connection = self._open_database()
        if connection is None:
            return 0

        sql = 'SELECT COUNT(*) FROM cdr_records'
        if where_clause:
            sql = '{} WHERE {}'.format(sql, where_clause)

        count = connection.execute(sql, params).fetchone()[0]
        connection.close()
        return count

    def _normalise_sql_rows(self, rows):
        """Return SQL result rows using the fixed shape expected by the frontend."""
        normalised = []
        for row in rows:
            keys = set(row.keys())
            record = {'si': row['si'] if 'si' in keys else ''}
            for column in self.required_cols:
                record[column] = row[column] if column in keys else ''
            normalised.append(record)
        return normalised

    def _execute_filter_sql(self, expression):
        """Run a read-only SQL filter and return frontend-ready records."""
        sql_text = (expression or '').strip()
        statement = sql_text[:-1].strip() if sql_text.endswith(';') else sql_text
        lowered = statement.lower()

        if ';' in statement:
            return {
                'success': False,
                'error': 'Only one SQL filter statement can be applied at a time.'
            }

        column_sql = ', '.join('"{}"'.format(col) for col in self.required_cols)
        if lowered.startswith('where '):
            statement = 'SELECT si, {} FROM cdr_records {} ORDER BY si'.format(
                column_sql,
                statement
            )
        elif not lowered.startswith('select '):
            return {
                'success': False,
                'error': 'SQL filters must start with WHERE or SELECT.'
            }

        connection = self._open_database()
        if connection is None:
            return {
                'success': False,
                'error': 'No CSV data loaded yet.'
            }

        try:
            connection.execute('PRAGMA query_only = ON')
            cursor = connection.execute(statement)
            rows = self._normalise_sql_rows(cursor.fetchall())
        except sqlite3.Error as exc:
            return {
                'success': False,
                'error': 'Invalid SQL filter: {}'.format(exc)
            }
        finally:
            connection.close()

        total_rows = self._count_records()
        return {
            'success': True,
            'count': len(rows),
            'total': total_rows,
            'filter_count': 1,
            'data': rows
        }

    def get_statistics(self):
        """Return statistics metadata for the frontend."""
        return self.statistics.get_previews()

    def get_suspicious_alerts(self):
        """Detect B-Parties associated with multiple device or subscriber IDs."""
        if not self.db_path:
            return {'success': True, 'count': 0, 'alerts': []}

        records = self._fetch_records()
        grouped = {}
        for row in records:
            a_party = str(row.get('A-Party', '')).strip()
            if not a_party:
                continue

            entry = grouped.setdefault(
                a_party,
                {'imeis': set(), 'imsis': set(), 'record_count': 0}
            )
            entry['record_count'] += 1

            imei = str(row.get('IMEI', '')).strip()
            imsi = str(row.get('IMSI', '')).strip()
            if imei:
                entry['imeis'].add(imei)
            if imsi:
                entry['imsis'].add(imsi)

        alerts = []
        for b_party, identifiers in grouped.items():
            multiple_imeis = len(identifiers['imeis']) > 1
            multiple_imsis = len(identifiers['imsis']) > 1
            if not multiple_imeis and not multiple_imsis:
                continue

            changed_identifiers = []
            if multiple_imeis:
                changed_identifiers.append('IMEI')
            if multiple_imsis:
                changed_identifiers.append('IMSI')

            alerts.append({
                'type': 'Multiple device/subscriber identifiers',
                'severity': 'High' if multiple_imeis and multiple_imsis else 'Medium',
                'b_party': b_party,
                'message': 'A-Party uses multiple {} values.'.format(
                    ' and '.join(changed_identifiers)
                ),
                'imeis': sorted(identifiers['imeis']),
                'imsis': sorted(identifiers['imsis']),
                'record_count': identifiers['record_count'],
            })

        alerts.sort(
            key=lambda alert: (
                0 if alert['severity'] == 'High' else 1,
                alert['b_party'].casefold(),
            )
        )
        return {'success': True, 'count': len(alerts), 'alerts': alerts}

    def open_statistics_window(self, statistic_id):
        """Open an interactive Matplotlib window for the selected statistic."""
        return self.statistics.open_window(statistic_id, self.db_path)
    
    def parse_csv(self, text):
        """Parse CSV text, including quoted commas and escaped quotes."""
        return list(csv.reader(io.StringIO(text)))
    
    def normalize_header(self, h):
        """Normalize header string"""
        return (h or '').strip().lower()
    
    def validate_headers(self, headers):
        """Validate and map CSV headers"""
        lower = [self.normalize_header(h) for h in headers]
        header_map = {}
        for col in self.required_cols:
            idx = -1
            try:
                idx = lower.index(col.lower())
            except ValueError:
                pass
            header_map[col] = idx
        return header_map
    
    def process_csv_data(self, text):
        """Parse, validate, and process CSV data"""
        rows = self.parse_csv(text)

        if not rows:
            return {'success': False, 'error': 'No data found in CSV.'}

        return self._process_parsed_rows(rows)

    def process_csv_file(self, file_path):
        """Load CSV data from a file path and stage it in a temporary SQLite database."""
        if not file_path or not str(file_path).strip():
            return {'success': False, 'error': 'No file path provided.'}

        if not os.path.isfile(file_path):
            return {'success': False, 'error': 'File not found: {}'.format(file_path)}

        try:
            with open(file_path, 'r', encoding='utf-8-sig', errors='replace', newline='') as csv_file:
                rows = list(csv.reader(csv_file))
        except OSError as exc:
            return {'success': False, 'error': 'Failed to read CSV file: {}'.format(exc)}

        return self._process_parsed_rows(rows)

    def _process_parsed_rows(self, rows):
        """Validate parsed rows and persist them to the temporary database."""
        if not rows:
            return {'success': False, 'error': 'No data found in CSV.'}

        headers = [str(h).strip() for h in rows[0]]
        header_map = self.validate_headers(headers)

        missing = [c for c in self.required_cols if header_map[c] == -1]
        if missing:
            return {'success': False, 'error': f'Missing columns: {", ".join(missing)}'}
        
        data_rows = []
        for r in rows[1:]:
            obj = {}
            for col in self.required_cols:
                idx = header_map[col]
                obj[col] = (r[idx] if idx >= 0 and idx < len(r) else '').strip()
            data_rows.append(obj)
        
        self.rows_data = data_rows
        self._store_rows_in_database(data_rows)
        self.statistics.generate_previews(data_rows)
        statistics = self.get_statistics()
        suspicious = self.get_suspicious_alerts()
        return {
            'success': True,
            'count': len(data_rows),
            'data': data_rows,
            'statistics': statistics['statistics'],
            'alerts': suspicious['alerts'],
        }
    
    def search_by_field(self, field, query):
        """Search rows by field value using SQLite."""
        canonical_field = self._canonical_field(field)
        if not canonical_field or not query or not self.db_path:
            return []

        like_value = '%{}%'.format(query.strip().casefold())
        where_clause = 'LOWER(COALESCE("{}", \'\')) LIKE ?'.format(canonical_field)
        matches = self._fetch_records(where_clause, (like_value,))
        return [{'si': row['si'], 'row': row} for row in matches]

    def _canonical_field(self, requested_field):
        """Return the configured column name matching a case-insensitive input."""
        normalized = self.normalize_header(requested_field)
        return next(
            (
                column
                for column in self.required_cols
                if self.normalize_header(column) == normalized
            ),
            None
        )

    def _parse_filter_expression(self, expression):
        """Parse comma-separated filters such as 'B-Party = 9876' or 'Duration > 60'."""
        filters = []
        invalid = []
        operators = ('>=', '<=', '!=', '>', '<', '=')

        for part in (expression or '').split(','):
            text = part.strip()
            if not text:
                continue

            field_text = ''
            separator = ''
            value = ''
            for operator in operators:
                if operator in text:
                    field_text, _, value = text.partition(operator)
                    separator = operator
                    break

            field = self._canonical_field(field_text)
            value = value.strip()

            if not separator or not field or not value:
                invalid.append(text)
                continue

            filters.append((field, separator, value))

        return filters, invalid

    def _build_filter_clause(self, field, operator, value):
        """Build one SQL WHERE clause for a parsed filter."""
        if field == 'Duration' and operator in {'=', '!=', '>', '<', '>=', '<='}:
            seconds = self._duration_seconds(value)
            if seconds is None:
                return None
            return 'DURATION_SECONDS("Duration") {} ?'.format(operator), seconds

        if field == 'Start Date' and operator in {'=', '!=', '>', '<', '>=', '<='}:
            date_key = self._date_key(value)
            if date_key is None:
                return None
            return 'DATE_KEY("Start Date") {} ?'.format(operator), date_key

        if operator == '=':
            return 'LOWER(COALESCE("{}", \'\')) LIKE ?'.format(field), '%{}%'.format(value.casefold())

        if operator == '!=':
            return 'LOWER(COALESCE("{}", \'\')) NOT LIKE ?'.format(field), '%{}%'.format(value.casefold())

        return 'LOWER(COALESCE("{}", \'\')) {} ?'.format(field, operator), value.casefold()

    def filter_records(self, expression):
        """Filter stored records using case-insensitive AND conditions in SQLite."""
        if not self.db_path:
            return {
                'success': False,
                'error': 'No CSV data loaded yet.'
            }

        if not (expression or '').strip():
            all_rows = self._fetch_records()
            return {
                'success': True,
                'count': len(all_rows),
                'total': len(all_rows),
                'filter_count': 0,
                'data': all_rows
            }

        stripped_expression = (expression or '').strip()
        lowered_expression = stripped_expression.lower()
        if lowered_expression.startswith('where ') or lowered_expression.startswith('select '):
            return self._execute_filter_sql(stripped_expression)

        filters, invalid = self._parse_filter_expression(expression)
        if invalid or not filters:
            return {
                'success': False,
                'error': (
                    'Invalid filter. Use: '
                    'B-Party = value, Duration > 60, Start Date <= 2026-06-01, '
                    'WHERE "B-Party" LIKE "%9876%", or '
                    'SELECT * FROM cdr_records WHERE "Call Type" = "OUT"'
                )
            }

        where_clauses = []
        params = []
        for field, operator, value in filters:
            clause = self._build_filter_clause(field, operator, value)
            if clause is None:
                return {
                    'success': False,
                    'error': 'Invalid value for {} comparison: {}'.format(field, value)
                }
            where_clause, param = clause
            where_clauses.append(where_clause)
            params.append(param)

        filtered_rows = self._fetch_records(' AND '.join(where_clauses), tuple(params))
        total_rows = self._count_records()

        return {
            'success': True,
            'count': len(filtered_rows),
            'total': total_rows,
            'filter_count': len(filters),
            'data': filtered_rows
        }

    def get_all_records(self):
        """Return the complete uploaded dataset for Refresh."""
        if not self.db_path:
            return {
                'success': True,
                'count': 0,
                'data': []
            }

        all_rows = self._fetch_records()
        return {
            'success': True,
            'count': len(all_rows),
            'data': all_rows
        }

    def export_cdr_pdf(self, records=None, filters=None):
        """Export displayed CDR records to PDF."""
        filters = filters or {}

        if records is None:
            records = self.get_all_records().get('data', [])
        if isinstance(records, dict):
            records = records.get('data', [])

        records = records or []
        output_path = self.export_data_dir / 'cdr_export.pdf'

        has_filters = False
        if isinstance(filters, dict):
            has_filters = any(str(v).strip() for v in filters.values() if v is not None)
            filter_text = ', '.join(
                '{}: {}'.format(k, v) for k, v in filters.items()
                if v is not None and str(v).strip()
            )
        else:
            filter_text = str(filters).strip()
            has_filters = bool(filter_text)

        doc = SimpleDocTemplate(str(output_path), pagesize=landscape(A4))
        styles = getSampleStyleSheet()
        elements = []

        elements.append(Paragraph('Filter' if has_filters else 'CDR Export', styles['Title']))
        elements.append(Spacer(1, 10))

        if has_filters and filter_text:
            elements.append(Paragraph('Applied filters: {}'.format(filter_text), styles['Normal']))
            elements.append(Spacer(1, 10))

        if not records:
            elements.append(Paragraph('No records to export.', styles['Normal']))
            doc.build(elements)
            return {'success': True, 'path': str(output_path)}

        headers = list(records[0].keys())
        data = [headers]
        for row in records:
            data.append([str(row.get(col, '')) for col in headers])

        table = Table(data, repeatRows=1)
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.black),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ]))
        elements.append(table)

        doc.build(elements)
        return {'success': True, 'path': str(output_path)}

    def __del__(self):
        self._close_database()


class Statistics:
    def __init__(self, temp_data_dir):
        self.temp_data_dir = Path(temp_data_dir)
        self.temp_data_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _pyplot(interactive=False):
        """Load pyplot with the backend required by the current process."""
        matplotlib.use('TkAgg' if interactive else 'Agg', force=True)
        import matplotlib.pyplot as plt
        return plt

    @staticmethod
    def _parse_date_value(value):
        text = (value or '').strip()
        if not text:
            return None

        for date_format in (
            '%Y-%m-%d', '%d-%m-%Y', '%d/%m/%Y', '%m/%d/%Y',
            '%Y/%m/%d', '%d-%b-%Y', '%d-%B-%Y',
        ):
            try:
                return datetime.strptime(text, date_format)
            except ValueError:
                continue
        return None

    def _file_map(self):
        return {
            'b_party_calls': self.temp_data_dir / 'b_party_calls.png',
            'calls_by_date': self.temp_data_dir / 'calls_by_date.png',
            'cell_id_calls': self.temp_data_dir / 'cell_id_calls.png',
        }

    def _build_items(self, statistic_id, values):
        counts = Counter((value or '').strip() or 'Unknown' for value in values)
        if statistic_id == 'b_party_calls':
            items = sorted(counts.items(), key=lambda item: (-item[1], item[0].casefold()))
            if len(items) > 15:
                other_total = sum(count for _, count in items[14:])
                items = items[:14] + ([('Other', other_total)] if other_total else [])
            return items, 'B-Party vs No. of Calls', 'B-Party', '#2563eb'

        if statistic_id == 'cell_id_calls':
            items = sorted(counts.items(), key=lambda item: (-item[1], item[0].casefold()))
            if len(items) > 15:
                other_total = sum(count for _, count in items[14:])
                items = items[:14] + ([('Other', other_total)] if other_total else [])
            return items, 'Cell ID vs No. of Calls', 'Cell ID', '#f59e0b'

        dated_items = [
            (label, count, self._parse_date_value(label))
            for label, count in counts.items()
        ]
        dated_items.sort(
            key=lambda item: (
                0 if item[2] is not None else 1,
                item[2] or item[0].casefold()
            )
        )
        items = [(label, count) for label, count, _ in dated_items]
        return items, 'No. of Calls vs Dates', 'Date', '#10b981'

    def _draw(self, statistic_id, values, interactive=False, output_path=None):
        plt = self._pyplot(interactive)
        items, title, x_label, color = self._build_items(statistic_id, values)
        labels = [label for label, _ in items]
        counts = [count for _, count in items]

        figure, axis = plt.subplots(figsize=(12, 6), dpi=160 if output_path else None)
        positions = list(range(len(labels)))
        axis.bar(positions, counts, color=color, edgecolor='#1f2937', linewidth=0.6)
        axis.set_xticks(positions)
        axis.set_xticklabels(labels, rotation=45, ha='right')
        axis.set_title(title, fontsize=14, fontweight='bold')
        axis.set_xlabel(x_label)
        axis.set_ylabel('No. of Calls')
        axis.grid(axis='y', linestyle='--', alpha=0.3)
        figure.tight_layout()

        if output_path:
            figure.savefig(output_path, bbox_inches='tight')
            plt.close(figure)
        else:
            figure.canvas.manager.set_window_title('CDR-IED Statistics')
            plt.show()

    def generate_previews(self, data_rows):
        values = {
            'b_party_calls': [row.get('B-Party', '') for row in data_rows],
            'calls_by_date': [row.get('Start Date', '') for row in data_rows],
            'cell_id_calls': [row.get('Cell ID', '') for row in data_rows],
        }
        for statistic_id, output_path in self._file_map().items():
            self._draw(statistic_id, values[statistic_id], output_path=output_path)

    def get_previews(self):
        titles = {
            'b_party_calls': 'Calls by B-Party',
            'calls_by_date': 'Calls by Date',
            'cell_id_calls': 'Calls by Cell ID',
        }
        previews = []
        for statistic_id, file_path in self._file_map().items():
            if file_path.is_file():
                encoded = base64.b64encode(file_path.read_bytes()).decode('ascii')
                previews.append({
                    'id': statistic_id,
                    'title': titles[statistic_id],
                    'preview': 'data:image/png;base64,{}'.format(encoded),
                })
        return {'success': True, 'count': len(previews), 'statistics': previews}

    def open_window(self, statistic_id, db_path):
        if statistic_id not in self._file_map():
            return {'success': False, 'error': 'Unknown statistic requested.'}
        if not db_path or not Path(db_path).is_file():
            return {'success': False, 'error': 'No CDR data is available.'}

        command = [
            sys.executable,
            str(Path(__file__).resolve().parent / 'app.py'),
            '--matplotlib-statistic',
            statistic_id,
            str(Path(db_path).resolve()),
        ]
        options = {}
        if sys.platform == 'win32':
            options['creationflags'] = subprocess.CREATE_NO_WINDOW
        try:
            subprocess.Popen(command, **options)
        except OSError as exc:
            return {'success': False, 'error': 'Unable to open Matplotlib window: {}'.format(exc)}
        return {'success': True}

    def show_window(self, statistic_id, db_path):
        """Build and display an interactive statistic directly from SQLite data."""
        statistic_columns = {
            'b_party_calls': 'B-Party',
            'calls_by_date': 'Start Date',
            'cell_id_calls': 'Cell ID',
        }
        if statistic_id not in statistic_columns:
            raise ValueError('Unknown statistic: {}'.format(statistic_id))
        if not Path(db_path).is_file():
            raise FileNotFoundError('CDR database not found: {}'.format(db_path))

        column = statistic_columns[statistic_id]
        connection = sqlite3.connect(db_path)
        try:
            rows = connection.execute(
                'SELECT COALESCE("{}", \'\') FROM cdr_records ORDER BY si'.format(column)
            ).fetchall()
        finally:
            connection.close()

        self._draw(statistic_id, [row[0] for row in rows], interactive=True)

