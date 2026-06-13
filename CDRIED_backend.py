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
        return connection

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

    def get_statistics(self):
        """Return statistics metadata for the frontend."""
        return self.statistics.get_previews()

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
        return {
            'success': True,
            'count': len(data_rows),
            'data': data_rows,
            'statistics': statistics['statistics'],
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
        """Parse comma-separated filters such as 'B-Party = 9876'."""
        filters = []
        invalid = []

        for part in (expression or '').split(','):
            text = part.strip()
            if not text:
                continue

            field_text, separator, value = text.partition('=')
            field = self._canonical_field(field_text)
            value = value.strip()

            if not separator or not field or not value:
                invalid.append(text)
                continue

            filters.append((field, value.casefold()))

        return filters, invalid

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

        filters, invalid = self._parse_filter_expression(expression)
        if invalid or not filters:
            return {
                'success': False,
                'error': (
                    'Invalid filter. Use: '
                    'B-Party = value, Call Type = value'
                )
            }

        where_clauses = []
        params = []
        for field, expected in filters:
            where_clauses.append('LOWER(COALESCE("{}", \'\')) LIKE ?'.format(field))
            params.append('%{}%'.format(expected))

        filtered_rows = self._fetch_records(' AND '.join(where_clauses), tuple(params))
        total_rows = self._fetch_records()

        return {
            'success': True,
            'count': len(filtered_rows),
            'total': len(total_rows),
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
        }

    def _build_items(self, statistic_id, values):
        counts = Counter((value or '').strip() or 'Unknown' for value in values)
        if statistic_id == 'b_party_calls':
            items = sorted(counts.items(), key=lambda item: (-item[1], item[0].casefold()))
            if len(items) > 15:
                other_total = sum(count for _, count in items[14:])
                items = items[:14] + ([('Other', other_total)] if other_total else [])
            return items, 'B-Party vs No. of Calls', 'B-Party', '#2563eb'

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
        }
        for statistic_id, output_path in self._file_map().items():
            self._draw(statistic_id, values[statistic_id], output_path=output_path)

    def get_previews(self):
        titles = {
            'b_party_calls': 'Calls by B-Party',
            'calls_by_date': 'Calls by Date',
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
        if statistic_id not in {'b_party_calls', 'calls_by_date'}:
            raise ValueError('Unknown statistic: {}'.format(statistic_id))
        if not Path(db_path).is_file():
            raise FileNotFoundError('CDR database not found: {}'.format(db_path))

        column = 'B-Party' if statistic_id == 'b_party_calls' else 'Start Date'
        connection = sqlite3.connect(db_path)
        try:
            rows = connection.execute(
                'SELECT COALESCE("{}", \'\') FROM cdr_records ORDER BY si'.format(column)
            ).fetchall()
        finally:
            connection.close()

        self._draw(statistic_id, [row[0] for row in rows], interactive=True)



