from airflow import DAG
from airflow.operators.python import PythonOperator, BranchPythonOperator
from airflow.operators.postgres_operator import PostgresOperator
from airflow.models.param import Param
from airflow.providers.postgres.hooks.postgres import PostgresHook

import pandas as pd
import logging

from datetime import datetime
from os.path import exists

doc_md_DAG = """
### NYC Airbnb ETL DAG

This DAG loads and transforms Airbnb host data from [Kaggle dataset](https://www.kaggle.com/datasets/dgomonov/new-york-city-airbnb-open-data/data).

The pipeline will load the transformed data into a PostgreSQL database and save it locally as well.
"""


def read_raw_data(path, **kwargs):
    if not exists(path):
        raise FileNotFoundError(f"File does not exist: {path}")

    try:
        df = pd.read_csv(path)
        if df.empty:
            raise ValueError("The file is empty or couldn't be read properly.")
        kwargs['ti'].xcom_push(key='raw_data', value=df.to_dict())
    except pd.errors.EmptyDataError:
        raise ValueError("The file is empty.")
    except pd.errors.ParserError:
        raise ValueError("Error occurred while parsing the file.")
    except Exception as e:
        raise RuntimeError(f"An error occurred while reading the file: {e}")


def transform_data(**kwargs):
    ti = kwargs['ti']
    raw_data = ti.xcom_pull(key='raw_data')
    if raw_data:
        df = pd.DataFrame(raw_data)

        df = df[df['price'] > 0]
        df['last_review'] = pd.to_datetime(df['last_review'])
        df['last_review'] = df['last_review'].fillna(datetime(2015, 8, 31))
        df['reviews_per_month'] = df['reviews_per_month'].fillna(0)
        df.drop(df[df['latitude'] == 0].index, inplace=True)
        df.drop(df[df['longitude'] == 0].index, inplace=True)

        df.to_csv('/opt/airflow/transformed/ab_nyc.csv', index=False)
    else:
        raise ValueError("No data found in XCom.")


def query_and_log_results(ti):
    hook = PostgresHook(postgres_conn_id='test-connection')

    table_result = hook.get_records("SELECT count(*) FROM airbnb_listings")

    df = pd.read_csv('/opt/airflow/transformed/ab_nyc.csv')
    if df.shape[0] != table_result[0][0]:
        ti.xcom_push(key='error_message', value='Row count mismatch between CSV and database table')
        return 'log_error_task'

    nullable = hook.get_records("SELECT COUNT(*) FROM airbnb_listings WHERE price IS NULL OR minimum_nights IS NULL OR availability_365 IS NULL")
    print(nullable)
    if nullable[0][0] != 0:
        ti.xcom_push(key='error_message', value='Null values found in essential columns')
        return 'log_error_task'

    return 'log_success_task'


def log_error(ti):
    error_message = ti.xcom_pull(task_ids='test_data', key='error_message')
    logging.error(f'Error: {error_message}')


def log_success():
    logging.info('all good')


with DAG(
    dag_id='nyc_airbnb_etl',
    start_date=datetime(2024, 8, 31),
    schedule_interval='30 6 * * *',
    params={
        'path': Param('/opt/airflow/raw/AB_NYC_2019.csv', type='string')
    },
    doc_md=doc_md_DAG
) as dag:
    read_data_task = PythonOperator(
        task_id='read_raw_data',
        python_callable=read_raw_data,
        op_args=['{{ params.path }}'],
        doc_md='Reads the data from file path specified at the start of the run'
    )

    transform_data_task = PythonOperator(
        task_id='transform_data',
        python_callable=transform_data,
        doc_md='Transforms data and cleans invalid entries'
    )

    write_task = PostgresOperator(
        task_id='write_data',
        postgres_conn_id='test-connection',
        sql="""
            TRUNCATE TABLE airbnb_listings;
            COPY airbnb_listings FROM '/transformed/transformed/ab_nyc.csv'
            DELIMITER ','
            CSV HEADER;
        """,
        doc_md='Reads transformed data and inserts it into PostgreSQL airbnb_listings table'
    )  # I know there should be duplicate data handling

    test_data = BranchPythonOperator(
        task_id='test_data',
        python_callable=query_and_log_results,
        provide_context=True,
        doc_md='Checks if data in PostgreSQL has been written and is valid'
    )

    log_success_task = PythonOperator(
        task_id='log_success_task',
        python_callable=log_success,
        doc_md='Runs if data was transformed and written without errors'
    )

    log_error_task = PythonOperator(
        task_id='log_error_task',
        python_callable=log_error,
        provide_context=True,
        doc_md='Runs if there are issues with data'
    )

    read_data_task >> transform_data_task >> write_task >> test_data >> [log_success_task, log_error_task]
