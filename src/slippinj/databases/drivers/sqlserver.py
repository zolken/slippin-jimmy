import pymssql
import re
import unicodedata

from injector import inject, AssistedBuilder


class Sqlserver(object):
    """Wrapper to connect to SQL Servers and get all the metastore information"""

    @inject(mssql=AssistedBuilder(callable=pymssql.connect), logger='logger')
    def __init__(self, mssql, logger, db_host=None, db_user='root', db_name=None, db_pwd=None, db_port=1433):
        """
        Initialize the SQLServer driver to get all the tables information
        :param mssql: Pymssql
        :param logger: Logger
        :param db_host: string
        :param db_user: string
        :param db_name: string
        :param db_pwd: string
        :param db_port: int
        """
        super(Sqlserver, self).__init__()

        self.__db_name = db_name
        self.__conn = mssql.build(server=db_host, user=db_user, password=db_pwd, database=db_name,
                                  port=db_port if None != db_port else 1433)

        self.__column_types = {
            'uniqueidentifier': 'string',
            'datetime': 'timestamp',
            'nvarchar': 'string',
            'money': 'double',
            'decimal': 'double',
            'bit': 'boolean',
            'float': 'double'
        }

        self.__illegal_characters = re.compile(r'[\000-\010]|[\013-\014]|[\016-\037]')

        self.__logger = logger

    def __join_tables_list(self, tables):
        return ','.join('\'%s\'' % table for table in tables)

    def __get_table_list(self, table_list_query=False):

        self.__logger.debug('Getting table list')
        query = 'SELECT table_name FROM information_schema.tables WHERE table_catalog = %(db_name)s and table_schema = %(schema)s {table_list_query}'.format(
            table_list_query=' AND ' + table_list_query if table_list_query else '')
        cursor = self.__conn.cursor(as_dict=True)
        cursor.execute(query, {'db_name': self.__db_name, 'schema': 'dbo'})

        self.__logger.debug('Found {count} tables'.format(count=cursor.rowcount))

        return map(lambda x: x['table_name'], cursor.fetchall())

    def __get_tables_to_exclude(self, tables):
        return self.__get_table_list('table_name NOT IN ({tables})'.format(tables=self.__join_tables_list(tables)))

    def __get_columns_for_tables(self, tables):

        self.__logger.debug('Getting columns information')
        info_query = 'SELECT table_name, column_name, data_type, character_maximum_length, is_nullable, column_default FROM information_schema.columns WHERE table_name IN ({tables}) AND table_catalog=%(db_name)s AND table_schema=%(schema)s'.format(
            tables=self.__join_tables_list(tables))

        cursor = self.__conn.cursor(as_dict=True)
        cursor.execute(info_query, {'db_name': self.__db_name, 'schema': 'dbo'})

        tables_information = {}
        for row in cursor.fetchall():
            self.__logger.debug(
                'Columns found for table {table}'.format(table=row['table_name']))
            if not row['table_name'] in tables_information:
                tables_information[row['table_name']] = {'columns': []}

            tables_information[row['table_name']]['columns'].append({
                'column_name': row['column_name'],
                'data_type': row['data_type'] if row['data_type'] not in self.__column_types else self.__column_types[
                    row['data_type']],
                'character_maximum_length': row['character_maximum_length'],
                'is_nullable': row['is_nullable'],
                'column_default': row['column_default'],
            })

        return tables_information

    def __get_count_for_tables(self, tables):

        tables_information = {}
        cursor = self.__conn.cursor()
        for table in tables:
            try:
                self.__logger.debug('Getting count for table {table}'.format(table=table))
                cursor.execute('SELECT COUNT(*) FROM {table}'.format(table=table))
                tables_information[table] = {'count': cursor.fetchone()[0]}
            except:
                pass

        return tables_information

    def _get_top_for_tables(self, tables, top=30):

        tables_information = {}

        cursor = self.__conn.cursor()
        for table in tables:
            tables_information[table] = {'rows': []}
            if top > 0:
                try:
                    self.__logger.debug('Getting {top} rows for table {table}'.format(top=top, table=table))
                    cursor.execute('SELECT TOP {top} * FROM {table}'.format(top=top, table=table))
                    for row in cursor.fetchall():
                        table_row = []
                        for column in row:
                            try:
                                if type(column) is unicode:
                                    column = unicodedata.normalize('NFKD', column).encode('iso-8859-1', 'ignore')
                                else:
                                    column = str(column).decode('utf8').encode('iso-8859-1')
                                    if self.__illegal_characters.search(column):
                                        column = 'Hexadecimal'
                            except:
                                column = 'Parse_error'

                            table_row.append(column)

                        tables_information[table]['rows'].append(table_row)

                except pymssql.ProgrammingError:
                    tables_information[table]['rows'].append(
                        'Error getting table data {error}'.format(error=pymssql.ProgrammingError.message))

        return tables_information

    def get_all_tables_info(self, table_list, table_list_query, top_max):
        """
        Return all the tables information reading from the Information Schema database
        :param table_list: string
        :param table_list_query: string
        :param top_max: integer
        :return: dict
        """
        tables_to_exclude = {}

        if table_list:
            tables = map(lambda x: unicode(x), table_list.split(','))
            tables_to_exclude = self.__get_tables_to_exclude(tables)
        else:
            tables = self.__get_table_list(table_list_query)

        tables_counts = self.__get_count_for_tables(tables)
        tables_columns = self.__get_columns_for_tables(tables)
        tables_top = self._get_top_for_tables(tables, top_max)

        tables_info = {'tables': {}}
        for table in tables_counts:
            tables_info['tables'][table] = {}
            tables_info['tables'][table].update(tables_columns[table])
            tables_info['tables'][table].update(tables_counts[table])
            tables_info['tables'][table].update(tables_top[table])

        if tables_to_exclude:
            tables_info['excluded_tables'] = tables_to_exclude

        return tables_info