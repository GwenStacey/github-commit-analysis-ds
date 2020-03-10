'''Borrowed utils file from Elisabeth Shah'''
from datetime import datetime
from decouple import config
import pandas as pd
import requests

from .models import DB, Repo
from .queries import repo_query, initial_PR_query, cont_PR_query
#Her original formatting for calling to the api
SECRET = config('SECRET')
URL = 'https://api.github.com/graphql'
DATE_FORMAT = '%Y-%m-%dT%H:%M:%SZ'
SECS_PER_HOUR = 3600

#Querying the api for the user and repo requested
def run_query(query, variables):
    r = requests.post(URL,
                      headers={'Authorization': 'token ' + SECRET, },
                      json={'query': query,
                            'variables': variables
                            })
    return r

#Pull in the repo and organize the data
def pull_repo(owner, name):
    variables = {'owner': owner, 'name': name}
    response = run_query(repo_query, variables)
    data = response.json()['data']['repository']

    data['repoName'] = data['name']
    data['stars'] = data['stars']['totalCount']
    data['owner'] = data['owner']['login']
    data['primaryLanguage'] = data['primaryLanguage']['name']
    data['totalIssues'] = data['totalIssues']['totalCount']
    data['openIssues'] = data['openIssues']['totalCount']
    data['closedIssues'] = data['closedIssues']['totalCount']
    data['totalPRs'] = data['totalPRs']['totalCount']
    data['openPRs'] = data['openPRs']['totalCount']
    data['mergedPRs'] = data['mergedPRs']['totalCount']
    data['closedPRs'] = data['closedPRs']['totalCount']
    data['vulnerabilityAlerts'] = data['vulnerabilityAlerts']['totalCount']

    if (data['mergedPRs'] + data['closedPRs'] != 0):
        data['PRacceptanceRate'] = data['mergedPRs'] / (data['mergedPRs'] +
                                                        data['closedPRs'])
    else:
        data['PRacceptanceRate'] = None
    data['createdAt'] = datetime.strptime(data['createdAt'],
                                          DATE_FORMAT)
    data['updatedAt'] = datetime.strptime(data['updatedAt'],
                                          DATE_FORMAT)
    data['ageInDays'] = (datetime.now().date() -
                         data['createdAt'].date()).days
    data['starsPerDay'] = data['stars'] / data['ageInDays']
    data['forksPerDay'] = data['forks'] / data['ageInDays']
    data['PRsPerDay'] = data['totalPRs'] / data['ageInDays']
    data['issuesPerDay'] = data['totalIssues'] / data['ageInDays']

    return data

#Summarize information contained within df
def summarize_PRs(pr_df):
    data = {}
    pr_df = pd.DataFrame(pr_df, index=[0])
    if pr_df.empty:
        data['uniquePRauthors'] = 0
        data['medianOpenPRhrsAge'] = None
        data['medianPRhrsToClose'] = None
        data['medianPRhrsToMerge'] = None
    else:
        #pr_df['author'] = [author.get('login') if author is not None else ''
        #                   for author in pr_df['author']]
        pr_df['createdAt'] = pd.to_datetime(pr_df['createdAt'],
                                            format=DATE_FORMAT)
        pr_df['closedAt'] = pd.to_datetime(pr_df['closedAt'],
                                           format=DATE_FORMAT)

        data['uniquePRauthors'] = pr_df['author'].nunique()

        openPRs = pr_df['state'] == 'OPEN'
        if openPRs.empty:
            data['medianOpenPRhrsAge'] = None
        else:
            openPRsecsAge = (datetime.now() -
                             pr_df['createdAt']).dt.total_seconds()[openPRs]
            data['medianOpenPRhrsAge'] = openPRsecsAge.median()/SECS_PER_HOUR

        closedPRs = pr_df['state'] == 'CLOSED'
        if closedPRs.empty:
            data['medianPRhrsToClose'] = None
        else:
            PRsecsToClose = (pr_df['closedAt'] -
                             pr_df['createdAt']).dt.total_seconds()[closedPRs]
            data['medianPRhrsToClose'] = PRsecsToClose.median()/SECS_PER_HOUR

        mergedPRs = pr_df['state'] == 'MERGED'
        if mergedPRs.empty:
            data['medianPRhrsToMerge'] = None
        else:
            PRsecsToMerge = (pr_df['closedAt'] -
                             pr_df['createdAt']).dt.total_seconds()[mergedPRs]
            data['medianPRhrsToMerge'] = PRsecsToMerge.median()/SECS_PER_HOUR

    return data


def add_or_update_repo(owner, name, app):
    repo_dict = pull_repo(owner, name)

    variables = {'owner': owner, 'name': name}
    response = run_query(initial_PR_query, variables)
    data = response.json()['data']
    df = pd.DataFrame.from_records(data['repository']['pullRequests']['nodes'])

    i = 0
    while data['repository']['pullRequests']['pageInfo']['hasNextPage']:
        i += 1
        yield 'Processing PRs {} to {} - '.format((i-1)*50, i*50)
        cursor = data['repository']['pullRequests']['pageInfo']['endCursor']
        variables['cursor'] = cursor
        response = run_query(cont_PR_query, variables)
        yield 'cursor {}.<br>'.format(cursor)
        data = response.json()['data']
        df = df.append(pd.DataFrame.from_records(
                data['repository']['pullRequests']['nodes']))

    pr_dict = summarize_PRs(df)
    repo_dict.update(pr_dict)

    db_repo = Repo(owner=repo_dict['owner'],
                   name=repo_dict['name'],
                   description=repo_dict['description'],
                   primary_language=repo_dict['primaryLanguage'],
                   created_at=repo_dict['createdAt'],
                   updated_at=repo_dict['updatedAt'],
                   disk_usage=repo_dict['diskUsage'],
                   stars=repo_dict['stars'],
                   forks=repo_dict['forks'],
                   total_issues=repo_dict['totalIssues'],
                   open_issues=repo_dict['openIssues'],
                   closed_issues=repo_dict['closedIssues'],
                   total_PRs=repo_dict['totalPRs'],
                   open_PRs=repo_dict['openPRs'],
                   merged_PRs=repo_dict['mergedPRs'],
                   closed_PRs=repo_dict['closedPRs'],
                   vulnerabilities=repo_dict['vulnerabilityAlerts'],
                   unique_PR_authors=repo_dict['uniquePRauthors'],
                   PR_acceptance_rate=repo_dict['PRacceptanceRate'],
                   median_open_PR_hrs_age=repo_dict['medianOpenPRhrsAge'],
                   median_PR_hrs_to_merge=repo_dict['medianPRhrsToMerge'],
                   median_PR_hrs_to_close=repo_dict['medianPRhrsToClose'],
                   )
    with app.app_context():
        DB.session.merge(db_repo)
        DB.session.commit()
    yield '{} {} added!'.format(owner, name)


def update_all_repos():
    for repo in Repo.query.all():
        add_or_update_repo(repo.owner, repo.name)