# Generated from: how_to_use.ipynb
# Converted at: 2026-10-21T16:20:41.456Z
# Next step (optional): refactor into modules & generate tests with RunCell
# Quick start: pip install runcell

# ## Welcome to Alpha Creation Engine (ACE)!
# ### This notebook is created to demonstrate functions of ACE that includes ace_lib.py and helpful_functions.py
# To ensure that functions will work properly - install the required libraries by running this cell:


!pip install -r requirements.txt

# Now, you need to import following modules:
# - **ace_lib** and **helpful_functions** - python modules that we provided for you to comfortably interact with [BRAIN API](https://platform.worldquantbrain.com/learn/documentation/brain-api/brain-api). [Documentation for ACE API Library](https://platform.worldquantbrain.com/learn/documentation/brain-api/ace-2023-doc).
# - **pandas** - is a useful python library for interacting with DataFrames and data analysis. [Pandas Documentation](https://pandas.pydata.org/docs/reference/frame.html)
# - **requests** - is a python library used for making requests for web services [Requests Documentation](https://requests.readthedocs.io/en/latest/)
# - **plotly.express** - is a python library that we will use for visualization. [Plotly.express Documentation](https://plotly.com/python/plotly-express/)
# - **tqdm** - is a library for creating progress bars. [tqdm Documentation](https://tqdm.github.io/)


import ace_lib as ace
import helpful_functions as hf
import pandas as pd
import plotly.express as px
from tqdm import tqdm

# ## Table of Contents:
# 1. [Start Session](#first-section)
#     - [Check Session timeout](#first-section-timeout)<br>
#     <br>
# 2. [Create list of Alpha Expressions](#second-section)
#     - [Step 1. Get datasets](#second-section-st1)
#     - [Step 2. Get data fields](#second-section-st2)
#     - [Step 3. Check available operators](#second-section-st3)
#     - [Step 4. Create expression list, using selected data fields](#second-section-st4)
#     - [Step 5. Apply `generate_alpha` function to the expression list](#second-section-st5)<br>
#     <br>
# 3. [Simulate Alpha list, get simulation result](#third-section)
#     - [Accessing the results of the simulation](#third-section-st1)<br>
#     <br>
# 4. [Working with `alpha_id` - main Alpha identificator](#fourth-section)
#     - [Yearly Statistics](#fourth-section-stats)
#     - [PnL](#fourth-section-pnl)
#     - [Self Correlation](#fourth-section-self)
#     - [Production Correlation](#fourth-section-prod)
#     - [Check Submission](#fourth-section-check)
#     - [Performance Comparison](#fourth-section-comparison)
#     - [Alpha Properties](#fourth-section-properties)
#     - [Mark Alphas by color](#fourth-section-mark)<br>
#     <br>
# 


# <a id='first-section'></a>
# ## 1. Start Session
# The initial step is to sign in, similar to how you would on the BRAIN platform. When you run the next cell, you'll be prompted to input your email and password. These are the same credentials you use to sign into the BRAIN.
# 
# After entering your credentials once, they will be locally saved and automatically loaded for future uses.
# 
# A session object, denoted as `s`, will be created upon successful login. This session object is important as it needs to be passed as an argument to every function that interacts with the BRAIN API. It serves as your authenticated link to the BRAIN API for all subsequent operations.


s = ace.start_session()

# <a id='first-section-timeout'></a>
# ### Check Session timeout
# To check how much time your Session will be live till logout, you can use `ace.check_session_timeout()` function. This function returns the number of seconds until the session expires, or 0 if the session has expired or an error occurred.


ace.check_session_timeout(s)

# Also you can use a function that checks session timeout and relogins if the remaining session time is less than 2000 seconds - `ace.check_session_and_relogin()`:


s = ace.check_session_and_relogin(s)

# <a id='second-section'></a>
# ## 2. Create list of Alpha Expressions
# <a id='second-section-st1'></a>
# ### Step 1. Get datsets
# We utilize the `get_datasets` function from the `ace_lib` module to download datasets. By default, when you use `ace.get_datasets(s)` (passing only the session as an argument), the function uses these default parameters: `instrument_type = 'EQUITY'`, `region = 'USA'`, `delay = 1`, `universe = 'TOP3000'`, and `theme = 'false'`.
# 
# If you wish to download datasets for a different region, delay, or universe, you must specify these parameters. For example, to download global datasets for the MINVOL1M universe, use: 
# ```python
# ace.get_datasets(
#     s, 
#     instrument_type='EQUITY', 
#     region='GLB', 
#     delay=1, 
#     universe='MINVOL1M', 
#     theme='true'
# )
# ```


datasets_df = ace.get_datasets(s)
datasets_df.head()

# Once you have the DataFrame with datasets, you can filter it based on the specific characteristics you're interested in for your research. This might include number of Alphas already created on this dataset, regions, or delay values, among other factors.
# 
# The most important column in `datasets_df` DataFrame is `id`. This column contains unique identifiers for each dataset.


selected_datasets_df = datasets_df[
    (datasets_df["delay"] == 1)
    & (datasets_df["coverage"] > 0)
    & (datasets_df["coverage"] <= 1)
    & (datasets_df["fieldCount"] > 0)
    & (datasets_df["fieldCount"] < 1000)
    & (datasets_df["region"] == "USA")
    & (datasets_df["universe"] == "TOP3000")
    & (datasets_df["userCount"] > 0)
    & (datasets_df["userCount"] < 1000)
    & (datasets_df["valueScore"] > 0)
    & (datasets_df["valueScore"] < 10)
    & (datasets_df["name"].str.contains("news", case=False))
    & ((datasets_df["category_id"] == "news") | (datasets_df["category_id"] == "analyst"))
].sort_values(by=["valueScore"], ascending=False)
selected_datasets_df.head()

# After you've identified the datasets you're interested in by filtering the DataFrame, you can use these `id` values to download the data fields associated with each dataset.


# <a id='second-section-st2'></a>
# ### Step 2. Get data fields
# In the following cell, we will compile all the selected dataset IDs into a list. Note that the get_datafields() function does not accept a list of dataset IDs; it takes a single dataset ID and downloads the associated data, returning it as a DataFrame.
# 
# To apply the function to all of the dataset IDs in your list, you can use a loop or a list comprehension.
# 
# We will hardcode `dataset_id` as `news18`. This means that we'll be working with the data from the dataset with the `id` `news18` in the following steps.


dataset_ids = selected_datasets_df.id.values.tolist()  # create a list of selected datasets ids
dataset_id = "news18"  # we will take news18 dataset for demonstration purpose

# The `get_datafields()` function from the `ace_lib` module is instrumental in fetching data. By default, it downloads data fields for USA, with a delay of 1, and for the universe TOP3000.
# 
# However, if you wish to use a specific dataset id from a different region, such as GLB, you must explicitly specify the `region`, `delay`, and `universe` in the `get_datafields()` function. If these are not specified, the function defaults to downloading data fields for the USA.
# 
# This is important because data fields from the same dataset might be available for one region and not available for another, leading to potential simulation errors.
# 
# In the next cell, we will not specify the region, so the data fields for USA, TOP3000, and delay 1 will be downloaded. If you wish to download data fields for another region, like GLB, you need to specifically include it as a parameter in the get_datafields() function. For example:<br> 
# ```python 
# def get_datafields(
#     s,
#     instrument_type = "EQUITY",
#     region = "USA",
#     delay = 1,
#     universe = "TOP3000",
#     search = "",
# ) -> pd.DataFrame:
# ```
# 
# ✅ That's right, you can 'search' for data fields by using this function, the same as you do in DataExplorer!
# 
# So, in the next cell we will download all data fields for USA, with a delay of 1, and for the universe TOP3000.  
# An then filter these fields, selecting those from `news18` dataset with `type=VECTOR`.


datafields_df = ace.get_datafields(s)
datafields_df.head()

filtered_datafields_df = datafields_df[
    (datafields_df['dataset_id'] == 'news18')
     & (datafields_df['type'] == 'VECTOR')
].reset_index(drop=True)
filtered_datafields_df.head()

# <a id='second-section-st3'></a>
# ### Step 3. Check available operators
# On previous step datafields with `data_type = "VECTOR"` were selected. ([Learn more about Vector Data Fields](https://platform.worldquantbrain.com/learn/documentation/understanding-data/vector-datafields)).
# 
# So you need to use `vec_` operator to aggregate vector data and transform it to a matrix. Then you can apply other operators, for example Time Series.
# 
# Use `get_operators()` function from `ace_lib` to load all available for you operators, then apply filtration and select needed operatos.


operators = ace.get_operators(s)
operators.head(10)

# Unique operator categories:


operators['category'].unique()

# Unique operator scopes:
# - `'REGULAR'` operator you can use in Alpha Expression,
# - `'SELECTION'` operator you can use in SuperAlpha Selection Expression,
# - `'COMBO'` operator you can use in SuperAlpha Combo Expression


operators['scope'].unique()

# As an example, here are all `Vector` operators available for `REGULAR` Alpha Expression:


operators[
    (operators['scope'] == 'REGULAR')
    & (operators['category'] == 'Vector')
]

# Additionally, take a look at `Time Series` operators available for `REGULAR` Alpha Expression:


operators[
    (operators['scope'] == 'REGULAR')
    & (operators['category'] == 'Time Series')
]

# ⚠️ Note: Check out available operators in other categories by yourself.


# <a id='second-section-st4'></a>
# ### Step 4. Create expression list, using selected data fields
# Now that we have the data and operators, let's generate an "Alpha Expression". An Alpha Expression is a string that you typically input this string into the simulation window on the BRAIN Platform.
# 
# In Python, you can create a list of Alpha expressions using *list comprehension*, a compact way to create lists based on existing ones.
# 
# In next line, we're creating a list of strings where each string is an Alpha expression. The `ts_sum(vec_avg({x}),120)` part of the string is a template for the expression, where `x` is replaced with each data field id from the DataFrame.
# 
# We're using the `vec_avg` operator because the data fields we loaded earlier are of type `'VECTOR'`. This operator calculates the average of a vector.
# 
# So, the `vec_avg({x})` part of the expression will calculate the average of the vector for each data field, and `ts_sum()` will then calculate the time-series sum of these averages over a window of 120 days.


expression_list = [f"ts_sum(vec_avg({x}),120)" for x in filtered_datafields_df.id.values.tolist()]

# Let's take a look at the first element of the `expression_list`:


print(expression_list[0])

# <a id='second-section-st5'></a>
# ### Step 5. Apply `generate_alpha` function to the expression list
# After creating the expression_list, you can now use the `generate_alpha` function from the `ace_lib`. 
# 
# By default, if you only pass an Alpha expression to this function, it will generate Alphas for USA, with a delay of 1 and the TOP3000 universe. 
# 
# However, `generate_alpha` allows you to specify various parameters to customize your Alpha:
# 
# ```python
# generate_alpha(
#     regular = 'ts_sum(vec_avg(nws18_acb),120)',
#     alpha_type = "REGULAR",
#     region = "GLB",
#     universe = "MINVOL1M",
#     delay = 1,
#     decay = 0,
#     neutralization = "INDUSTRY",
#     truncation = 0.08,
#     pasteurization = "ON",
#     test_period = "P2Y",
#     unit_handling = "VERIFY",
#     nan_handling = "OFF",
#     max_trade = "OFF",
#     visualization = False,
#     simulation_mode = "QUICK",
# )
# ```
# This function constructs an Alpha using the parameters you specify.
# 
# ⚠️ It's important to specify the correct values for region, universe, delay. If these parameters do not match the available options, your simulations will fail. 
# 
# To verify the available parameters, you can use the `get_instrument_type_region_delay(s)` function from `ace_lib`, which gives you a list of the acceptable values for each parameter.


ace.get_instrument_type_region_delay(s)

alpha_list = [
    ace.generate_alpha(
        x,
        region="USA",
        universe="TOP3000",
        test_period = "P2Y",
    )
    for x in expression_list
]

# Take a look at the first element of alpha_list:


alpha_list[0]

# This is an example - how Alpha actually looks like when you send it to the platform.


# <a id='third-section'></a>
# ## 3. Simulate Alpha list, get simulation result
# 
# The `simulate_alpha_list_multi` function runs multiple simulations concurrently when given a list of Alphas. If the list contains more than 10 Alphas, it will automatically perform a multi-simulation.  
# The function returns an object that includes the simulation results for all the Alphas as a list.  
# It's important to note that all Alphas in a single list should have the same region and delay settings when sent for multi-simulation.  
# By default, `simulate_alpha_list_multi` is set to run 3 concurrent simulations, with each simulation consisting of 3 multi-simulations of Alphas.  
# These defaults can be adjusted using the `limit_of_concurrent_simulations` and `limit_of_multi_simulations` parameters, maximum value for both is 8. 
# 
# Here's an example function call:
# 
# ```python
# simulate_alpha_list_multi(
#     s,
#     alpha_list,
#     limit_of_concurrent_simulations=3,
#     limit_of_multi_simulations=10,
#     simulation_config=DEFAULT_CONFIG,
# )
# ```
# 
# In this example, `s` is the current session, `alpha_list` is your list of Alphas, and `DEFAULT_CONFIG` is predefined simulation configuration.
# 
# 
# In the next step, you will simulate Alphas from `alpha_list`, and the results will be stored in the `result` variable.


len(alpha_list)

result = ace.simulate_alpha_list_multi(s, alpha_list[:])

# <a id='third-section-st1'></a>
# ### Accessing the results of the simulation
# <br>
# Take a look at the collected characteristics of first simulated Alpha:


result[0].keys()

# And here is how the result for first Alpha looks like:<br>
# - `alpha_id` - is an Alpha identificator on the BRAIN platform


result[0]['alpha_id']

# You can see this Alpha on the platfrom:


print(f'https://platform.worldquantbrain.com/alpha/{result[0]["alpha_id"]}')

# - `simulate_data` - is an Alpha that we sent to simulation, and its settings


result[0]['simulate_data']

# - Alpha aggregate InSample stats are in `is_stats`


result[0]["is_stats"]

# - Alpha InSample tests are in `is_tests`


result[0]['is_tests']

# The `prettify_result()` function from the `helpful_functions` module helps in organizing the simulation results of all Alphas into a neat DataFrame. 
# 
# Here's how you can use it:
# 
# ```python
# hf.prettify_result(result, detailed_tests_view=False, clickable_alpha_id = False)
# ```
# 
# - `result` is the simulation result returned by the `simulate_alpha_list_multi` function. 
# - `detailed_tests_view=False` means that the function will not display detailed test views in the DataFrame.
# - `clickable_alpha_id = False` means that the function will not make the Alpha ID in the DataFrame clickable.
# 
# So, in simple terms, the `prettify_result` function takes the raw results from your Alpha simulations and organizes them into a neat and easy-to-read DataFrame. It also provides options to include detailed test views and clickable Alpha IDs, based on your preference.


hf.prettify_result(result, clickable_alpha_id=True)

# <a id='fourth-section'></a>
# ## 4. Working with `alpha_id` &mdash; main Alpha identificator
# 
# Next, we'll work more with the `alpha_id`. This identifier allows us to gather additional statistics about the Alpha, check correlations and more.<br>
# In the subsequent functions we'll be using, the main parameters are `s` (the session object) and `alpha_id` (the identifier for an Alpha). <br>So, to make this process easier, we'll save the first `alpha_id` from the `result` into a variable. This way, we can easily use this `alpha_id` in the following function calls:


alpha_id = result[0]['alpha_id']
alpha_id

# Now we can use this id to get prod correlations, self correlations, submission checks, performance comparisons, set Alpha properties, and get PnL and yearly stats.


# <a id='fourth-section-stats'></a>
# ### Yearly Statistics
# The `get_alpha_yearly_stats()` function allows us to retrieve yearly statistics for our Alpha. <br>
# The DataFrame returned by this function includes all the standard IS Summary statistics, along with an additional `alpha_id` column specifying the Alpha these statistics correspond to.


ace.get_alpha_yearly_stats(s, alpha_id)

# <a id='fourth-section-pnl'></a>
# ### PnL
# You can get PnL data for your Alpha using the `get_alpha_pnl()` function.


alpha_pnl = ace.get_alpha_pnl(s, alpha_id)
alpha_pnl.head()

# The DataFrame returned by the `get_alpha_pnl()` function provides the Profit and Loss (PnL) information about a specific Alpha for different dates.
# 
# - The `Date` index: This represents the date of each record. The PnL values are sorted by date.
# - `pnl` column: This shows the Profit and Loss for the Alpha on a specific date. 
# - `alpha_id` column: This is the identifier for the Alpha. 


fig = px.line(alpha_pnl, x=alpha_pnl.index, y='pnl')

fig.update_layout(
    title=dict(text=f'<b>alpha_id={hf.make_clickable_alpha_id(alpha_pnl.alpha_id.iloc[0])}</b>', x=0.5),
    xaxis_title='Date',
    yaxis_title='Pnl',
)

fig.show()

# This graph shows the Alpha's Profit and Loss (PnL) over time, mirroring the view on the BRAIN platform. You can verify this by clicking the `alpha_id` in the title, which redirects you to the same Alpha on the BRAIN platform.


# <a id='fourth-section-self'></a>
# ### Self Correlation
# 
# Let's get the self correlation of an Alpha using the `get_self_corr()` function.


self_corr = ace.get_self_corr(s, alpha_id)
self_corr

# The DataFrame returned by the `get_self_corr()` function contains details about the Alpha's self-correlation with other Alphas in the same region.
# 
# - `id`: The unique identifier of the correlated Alpha.
# - `name`: The name of the correlated Alpha.
# - `instrumentType`: The instrument rype of the correlated Alpha.
# - `region`: The region of the correlated Alpha.
# - `universe`: The universe of the correlated Alpha.
# - `correlation`: The correlation between the Alpha and the correlated Alpha.
# - `sharpe`: The Sharpe ratio of the correlated Alpha. 
# - `returns`: The returns of the correlated Alpha.
# - `turnover`: The turnover of the correlated Alpha. 
# - `fitness`: The fitness of the correlated Alpha. 
# - `margin`: The margin of the correlated Alpha. 
# - `alpha_id`: The Alpha id that was used to fetch these correlations. 
# 
# So, this DataFrame provides a comprehensive view of how the specified Alpha correlates with other Alphas, along with other key information about these correlated Alphas.


# <a id='fourth-section-prod'></a>
# ### Production Correlation
# 
# We can get the production correlation of an Alpha by using the `get_prod_corr()` function.<br>


prod_corr = ace.get_prod_corr(s, alpha_id)
prod_corr

# This DataFrame returned from `get_prod_corr()` function represents the distribution of correlations of the Alpha denoted by `alpha_id` with other production Alphas.
# <br>
# - `min` and `max` columns represent the lower and upper bounds of each correlation bin (i.e., range of correlation values).
# - `alphas` column shows the number of production Alphas that fall within each bin. 
# - `alpha_id` column is the ID of the Alpha for which these correlations were calculated.<br>
# 
# Next, we'll visualize the dataframe containing production correlations.
# <br>
# Once we plot it, you'll notice that it closely resembles the representation on the BRAIN platform. To verify this, you can click on the `alpha_id` in the plot. This will redirect you to the corresponding Alpha on the BRAIN platform, allowing you to see the similarities for yourself.


fig = px.bar(prod_corr, x=[f"{row['min']}...{row['max']}" for index, row in prod_corr.iterrows()], y='alphas')

fig.update_layout(
    title=dict(text=f'<b>alpha_id={hf.make_clickable_alpha_id(prod_corr.alpha_id[0])}</b>', x=0.5),
    xaxis_title='Range',
    yaxis_title='№ Production Alphas',
)
fig.update_yaxes(type='log')

fig.show()

# <a id='fourth-section-check'></a>
# ### Check Submission
# 
# You can check if the Alpha can be submitted using the `get_check_submission()` function.


ace.get_check_submission(s, alpha_id)

# The DataFrame returned by the `get_check_submission()` function captures the results of various checks performed on the Alpha identified by `alpha_id`.
# 
# - `date`: The date on which the check was conducted. 'NaN' denotes the check is not date-specific or the date data is not available.
# - `limit`: The threshold value for the check. The `result` of the check is determined by comparing this limit with the `value`.
# - `name`: The name of the check that was performed.
# - `result`: The result of the check. It can be 'PASS', 'FAIL', 'PENDING', 'WARNING'
# - `value`: The value obtained from the check. This is compared with the `limit` to determine the `result`.
# - `alpha_id`: The id of the Alpha that these checks correspond to. 
# 
# So, this DataFrame provides an overview of the results of various checks performed on a specific Alpha.<br>
# ⚠️ Please note, an Alpha cannot be submitted if any of its test results are marked as 'FAIL'. <br>
# ⚠️ Please note, that if any tests FAIL after performing a simulation, there's no need to use the `get_check_submission()` function. This is because it will only consume time without providing any additional meaningful information. Instead, you can directly retrieve the test statuses from the Alpha simulation results:


# <a id='fourth-section-comparison'></a>
# ### Performance Comparison
# 
# The `performance_comparison()` function helps to understand the potential impact of a specific Alpha on the overall performance of your Alpha pool.<br>
# By examining the comparison data, you can make informed decisions about whether to submit a specific Alpha in your Alpha pool based on its potential to improve the overall performance.<br>
# This function is particularly useful in competitions.<br>
# The `performance_comparison()` function returns a dictionary representing the potential impact of a specific Alpha, denoted by `alpha_id`, on the overall performance of your Alpha pool:
# ```python 
# performance_comparison(s, alpha_id, team_id, competition)
# ```
# 
# If `team_id` is provided, the function compares the performance of the Alpha against the performance of the specified team. By default `team_id` is not specified.<br>
# If `competition` is provided, it compares the performance in the specified competition. By default `competition` is not specified.<br>
# If neither is provided, the function defaults to comparing the Alpha's performance against the user's own pool.


performance_comparison = ace.performance_comparison(s, alpha_id)

performance_comparison.keys()

# - In the `stats` section, you can find the performance metrics of your merged performance both before and after Alpha submission.


performance_comparison['stats']

# - In `yearlyStats` section you can find yearly statistics of yuour merged performance both before and after Alpha submission
# - In `PnL` section you can find PnL of your merged performance both before and after Alpha submission
# - If you specified a `competition` with merged performance score, then in `score` section you will find before and after submission score


# <a id='fourth-section-properties'></a>
# ### Alpha Properties
# By using `set_alpha_properties` from `ace_lib` you can set name, color, tag, descriprion to your Alpha or SuperAlpha.
# 
# Once function is applied you can check result on the platform.
# ```python 
# ace.set_alpha_properties(s: SingleSession,
#     alpha_id,
#     name = None,
#     color = None,
#     category = None,
#     regular_desc = None,
#     selection_desc = 'None',
#     combo_desc = 'None',
#     osmosis_points = None,
#     tags = None,
# ) -> requests.Response:
# ```
# Here is an example:


set_alpha_properties_response = ace.set_alpha_properties(
    s, alpha_id, name='MyAlpha', color='PURPLE', tags=['tag1', 'tag2']
)
set_alpha_properties_response

# `<Response [200]>` here means that properties are successfully set for an Alpha.
# You can check furter by applying `.json` to the response:


resonse = set_alpha_properties_response.json()

print(
    f"id: {resonse.get('id')}\n"
    f"color: {resonse.get('color')}\n"
    f"tags: {resonse.get('tags')}"
)

# Or you can check on the platform:


print(f'https://platform.worldquantbrain.com/alpha/{alpha_id}')

# <a id='fourth-section-mark'></a>
# ### Mark Alphas by color
# By using above functions you can implement your own logic how to mark Alphas that you want to improve further.
# 
# For example, below is a code snippet marks Alphas with specific colors based on certain conditions:
# - If any in-sample test result is 'FAIL' and if the Sharpe ratio in the training statistics is greater than 0.7 Alpha color is set to YELLOW
# - If no in-sample test result is 'FAIL':
#   - It retrieves the check submission for the Alpha using `ace.get_check_submission`.
#   - If no result in the check submission DataFrame is 'FAIL', it sets the color of the Alpha to 'GREEN'.
# 
# So, the code marks Alphas with 'YELLOW' if they have failed any in-sample tests but have a high Sharpe ratio, and with 'GREEN' if they have passed all in-sample and check submission tests.


for x in result:
    is_tests_df = x['is_tests']
    train_stats = x['train']
    alpha_id = x['alpha_id']
    if any(is_tests_df['result'] == 'FAIL') & (train_stats['sharpe'] > 0.7):
        ace.set_alpha_properties(s, alpha_id, color='YELLOW')
    elif not any(is_tests_df == 'FAIL'):
        check_submission_df = ace.get_check_submission(s, alpha_id)
        if not any(check_submission_df['result'] == 'FAIL'):
            ace.set_alpha_properties(s, alpha_id, color='GREEN')

passed_alphas = alpha_ids_with_no_failures