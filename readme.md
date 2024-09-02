### NYC Airbnb ETL DAG

This DAG loads and transforms Airbnb host data from [Kaggle dataset](https://www.kaggle.com/datasets/dgomonov/new-york-city-airbnb-open-data/data).

The pipeline will load the transformed data into a PostgreSQL database and save it locally as well.

### Tasks
* **read_data_task** - reads the data from file path specified at the start of the run
* **transform_data_task** - transforms data and cleans invalid entries
* **write_task** - reads transformed data and inserts it into PostgreSQL airbnb_listings table
* **test_data** - checks if data in PostgreSQL has been written and is valid

### Run
1. In terminal run `docker compose up`
2. In browser go to http://localhost:8080/dags and select `nyc_airbnb_etl` 
3. Enter `path` to raw data file (make sure that it's in docker container as well) or run DAG with default param
4. To check the data you can open postgres container within airflow-docker container and query the data with psql