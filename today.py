"""
Updates dark_mode.svg and light_mode.svg with my uptime (age) and GitHub stats.
Adapted from Andrew6rant's profile README script: https://github.com/Andrew6rant/Andrew6rant
"""
import datetime
import hashlib
import os
import time

import requests
from dateutil import relativedelta
from lxml import etree

# Personal access token with read access to all repositories, followers and starring
HEADERS = {'authorization': 'token ' + os.environ['ACCESS_TOKEN']}
USER_NAME = os.environ['USER_NAME']
BIRTHDAY = datetime.datetime(2000, 1, 13)
CACHE_COMMENT_SIZE = 7
CACHE_FILE = 'cache/' + hashlib.sha256(USER_NAME.encode('utf-8')).hexdigest() + '.txt'
QUERY_COUNT = {'user_getter': 0, 'follower_getter': 0, 'graph_repos_stars': 0, 'recursive_loc': 0, 'loc_query': 0}
OWNER_ID = None


def daily_readme(birthday):
    """
    Returns the length of time since I was born, e.g. 'XX years, XX months, XX days'
    """
    diff = relativedelta.relativedelta(datetime.datetime.today(), birthday)
    return '{} {}, {} {}, {} {}{}'.format(
        diff.years, 'year' + format_plural(diff.years),
        diff.months, 'month' + format_plural(diff.months),
        diff.days, 'day' + format_plural(diff.days),
        ' 🎂' if (diff.months == 0 and diff.days == 0) else '')


def format_plural(unit):
    return 's' if unit != 1 else ''


def simple_request(func_name, query, variables):
    """
    Returns a request, or raises an Exception if the response does not succeed
    """
    request = requests.post('https://api.github.com/graphql', json={'query': query, 'variables': variables}, headers=HEADERS, timeout=60)
    if request.status_code == 200:
        return request
    raise Exception(func_name, ' has failed with a', request.status_code, request.text, QUERY_COUNT)


def graph_repos_stars(count_type, owner_affiliation, cursor=None):
    """
    Uses GitHub's GraphQL v4 API to return my total repository or star count
    """
    query_count('graph_repos_stars')
    query = '''
    query ($owner_affiliation: [RepositoryAffiliation], $login: String!, $cursor: String) {
        user(login: $login) {
            repositories(first: 100, after: $cursor, ownerAffiliations: $owner_affiliation) {
                totalCount
                edges {
                    node {
                        ... on Repository {
                            nameWithOwner
                            stargazers {
                                totalCount
                            }
                        }
                    }
                }
                pageInfo {
                    endCursor
                    hasNextPage
                }
            }
        }
    }'''
    variables = {'owner_affiliation': owner_affiliation, 'login': USER_NAME, 'cursor': cursor}
    repositories = simple_request(graph_repos_stars.__name__, query, variables).json()['data']['user']['repositories']
    if count_type == 'repos':
        return repositories['totalCount']
    stars = sum(edge['node']['stargazers']['totalCount'] for edge in repositories['edges'] if edge and edge.get('node'))
    if repositories['pageInfo']['hasNextPage']:
        stars += graph_repos_stars(count_type, owner_affiliation, repositories['pageInfo']['endCursor'])
    return stars


def recursive_loc(owner, repo_name, data, cache_comment, addition_total=0, deletion_total=0, my_commits=0, cursor=None):
    """
    Uses GitHub's GraphQL v4 API and cursor pagination to fetch 100 commits from a repository at a time
    """
    query_count('recursive_loc')
    query = '''
    query ($repo_name: String!, $owner: String!, $cursor: String) {
        repository(name: $repo_name, owner: $owner) {
            defaultBranchRef {
                target {
                    ... on Commit {
                        history(first: 100, after: $cursor) {
                            totalCount
                            edges {
                                node {
                                    ... on Commit {
                                        committedDate
                                    }
                                    author {
                                        user {
                                            id
                                        }
                                    }
                                    deletions
                                    additions
                                }
                            }
                            pageInfo {
                                endCursor
                                hasNextPage
                            }
                        }
                    }
                }
            }
        }
    }'''
    variables = {'repo_name': repo_name, 'owner': owner, 'cursor': cursor}
    # Not using simple_request() so the cache can be saved before raising
    request = requests.post('https://api.github.com/graphql', json={'query': query, 'variables': variables}, headers=HEADERS, timeout=60)
    if request.status_code == 200:
        if request.json()['data']['repository']['defaultBranchRef'] is not None:
            return loc_counter_one_repo(owner, repo_name, data, cache_comment, request.json()['data']['repository']['defaultBranchRef']['target']['history'], addition_total, deletion_total, my_commits)
        return 0
    force_close_file(data, cache_comment)
    if request.status_code == 403:
        raise Exception('Too many requests in a short amount of time!\nYou\'ve hit the non-documented anti-abuse limit!')
    raise Exception('recursive_loc() has failed with a', request.status_code, request.text, QUERY_COUNT)


def loc_counter_one_repo(owner, repo_name, data, cache_comment, history, addition_total, deletion_total, my_commits):
    """
    Only adds the LOC value of commits authored by me, paging through history 100 commits at a time
    """
    for node in history['edges']:
        if node['node']['author']['user'] == OWNER_ID:
            my_commits += 1
            addition_total += node['node']['additions']
            deletion_total += node['node']['deletions']

    if history['edges'] == [] or not history['pageInfo']['hasNextPage']:
        return addition_total, deletion_total, my_commits
    return recursive_loc(owner, repo_name, data, cache_comment, addition_total, deletion_total, my_commits, history['pageInfo']['endCursor'])


def loc_query(owner_affiliation, comment_size=0, force_cache=False, cursor=None, edges=None):
    """
    Queries all the repositories I have access to (with respect to owner_affiliation), 60 at a time
    since larger or smaller queries tend to hit 502 errors. Returns the total lines of code.
    """
    edges = edges or []
    query_count('loc_query')
    query = '''
    query ($owner_affiliation: [RepositoryAffiliation], $login: String!, $cursor: String) {
        user(login: $login) {
            repositories(first: 60, after: $cursor, ownerAffiliations: $owner_affiliation) {
            edges {
                node {
                    ... on Repository {
                        nameWithOwner
                        defaultBranchRef {
                            target {
                                ... on Commit {
                                    history {
                                        totalCount
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
                pageInfo {
                    endCursor
                    hasNextPage
                }
            }
        }
    }'''
    variables = {'owner_affiliation': owner_affiliation, 'login': USER_NAME, 'cursor': cursor}
    repositories = simple_request(loc_query.__name__, query, variables).json()['data']['user']['repositories']
    edges += [edge for edge in repositories['edges'] if edge and edge.get('node')]
    if repositories['pageInfo']['hasNextPage']:
        return loc_query(owner_affiliation, comment_size, force_cache, repositories['pageInfo']['endCursor'], edges)
    return cache_builder(edges, comment_size, force_cache)


def cache_builder(edges, comment_size, force_cache, loc_add=0, loc_del=0):
    """
    Checks each repository to see if it has been updated since it was last cached,
    and if so re-runs recursive_loc on that repository to update its LOC count
    """
    cached = True
    try:
        with open(CACHE_FILE, 'r') as f:
            data = f.readlines()
    except FileNotFoundError:
        data = ['This line is a comment block. Write whatever you want here.\n'] * comment_size
        with open(CACHE_FILE, 'w') as f:
            f.writelines(data)

    if len(data) - comment_size != len(edges) or force_cache:
        cached = False
        flush_cache(edges, CACHE_FILE, comment_size)
        with open(CACHE_FILE, 'r') as f:
            data = f.readlines()

    cache_comment = data[:comment_size]
    data = data[comment_size:]
    for index in range(len(edges)):
        repo_hash, commit_count, *__ = data[index].split()
        if repo_hash == hashlib.sha256(edges[index]['node']['nameWithOwner'].encode('utf-8')).hexdigest():
            try:
                if int(commit_count) != edges[index]['node']['defaultBranchRef']['target']['history']['totalCount']:
                    owner, repo_name = edges[index]['node']['nameWithOwner'].split('/')
                    loc = recursive_loc(owner, repo_name, data, cache_comment)
                    data[index] = repo_hash + ' ' + str(edges[index]['node']['defaultBranchRef']['target']['history']['totalCount']) + ' ' + str(loc[2]) + ' ' + str(loc[0]) + ' ' + str(loc[1]) + '\n'
            except TypeError:  # empty repository
                data[index] = repo_hash + ' 0 0 0 0\n'
    with open(CACHE_FILE, 'w') as f:
        f.writelines(cache_comment)
        f.writelines(data)
    for line in data:
        loc = line.split()
        loc_add += int(loc[3])
        loc_del += int(loc[4])
    return [loc_add, loc_del, loc_add - loc_del, cached]


def flush_cache(edges, filename, comment_size):
    """
    Wipes the cache file (keeping the comment block). Called when the number of repositories changes.
    """
    with open(filename, 'r') as f:
        data = f.readlines()[:comment_size] if comment_size > 0 else []
    with open(filename, 'w') as f:
        f.writelines(data)
        for node in edges:
            f.write(hashlib.sha256(node['node']['nameWithOwner'].encode('utf-8')).hexdigest() + ' 0 0 0 0\n')


def force_close_file(data, cache_comment):
    """
    Saves whatever is in the cache before the program crashes
    """
    with open(CACHE_FILE, 'w') as f:
        f.writelines(cache_comment)
        f.writelines(data)
    print('There was an error while writing to the cache file. The file,', CACHE_FILE, 'has had the partial data saved and closed.')


def commit_counter(comment_size):
    """
    Counts up my total commits, using the cache file created by cache_builder
    """
    with open(CACHE_FILE, 'r') as f:
        data = f.readlines()[comment_size:]
    return sum(int(line.split()[2]) for line in data)


def svg_overwrite(filename, age_data, commit_data, star_data, repo_data, contrib_data, follower_data, loc_data):
    """
    Updates the SVG elements with my age, commits, stars, repositories, followers and lines of code.
    Lengths are the width (in characters) the dots + value should fill so the columns stay aligned.
    """
    tree = etree.parse(filename)
    root = tree.getroot()
    contrib_text = '{:,}'.format(contrib_data)
    justify_format(root, 'age_data', age_data, 47)
    justify_format(root, 'repo_data', repo_data, 9 - len(contrib_text))
    find_and_replace(root, 'contrib_data', contrib_text)
    justify_format(root, 'star_data', star_data, 14)
    justify_format(root, 'commit_data', commit_data, 23)
    justify_format(root, 'follower_data', follower_data, 10)
    justify_format(root, 'loc_data', loc_data[2], 9)
    find_and_replace(root, 'loc_add', loc_data[0])
    justify_format(root, 'loc_del', loc_data[1], 7)
    tree.write(filename, encoding='utf-8', xml_declaration=True)


def justify_format(root, element_id, new_text, length=0):
    """
    Updates the text of the element and resizes the dots before it so the value stays right-aligned
    """
    if isinstance(new_text, int):
        new_text = '{:,}'.format(new_text)
    new_text = str(new_text)
    find_and_replace(root, element_id, new_text)
    pad = length - len(new_text)
    dot_string = ' ' + '.' * (pad - 2) + ' ' if pad >= 3 else ' ' * max(pad, 1)
    find_and_replace(root, f'{element_id}_dots', dot_string)


def find_and_replace(root, element_id, new_text):
    element = root.find(f".//*[@id='{element_id}']")
    if element is not None:
        element.text = new_text


def user_getter(username):
    """
    Returns the account ID and creation time of the user
    """
    query_count('user_getter')
    query = '''
    query($login: String!){
        user(login: $login) {
            id
            createdAt
        }
    }'''
    request = simple_request(user_getter.__name__, query, {'login': username})
    return {'id': request.json()['data']['user']['id']}, request.json()['data']['user']['createdAt']


def follower_getter(username):
    """
    Returns the number of followers of the user
    """
    query_count('follower_getter')
    query = '''
    query($login: String!){
        user(login: $login) {
            followers {
                totalCount
            }
        }
    }'''
    request = simple_request(follower_getter.__name__, query, {'login': username})
    return int(request.json()['data']['user']['followers']['totalCount'])


def query_count(funct_id):
    QUERY_COUNT[funct_id] += 1


def perf_counter(funct, *args):
    """
    Returns the function result and the time it took to run
    """
    start = time.perf_counter()
    funct_return = funct(*args)
    return funct_return, time.perf_counter() - start


def formatter(query_type, difference):
    print('{:<23}'.format('   ' + query_type + ':'), end='')
    print('{:>12}'.format('%.4f' % difference + ' s ') if difference > 1 else '{:>12}'.format('%.4f' % (difference * 1000) + ' ms'))


if __name__ == '__main__':
    print('Calculation times:')
    (OWNER_ID, acc_date), user_time = perf_counter(user_getter, USER_NAME)
    formatter('account data', user_time)
    age_data, age_time = perf_counter(daily_readme, BIRTHDAY)
    formatter('age calculation', age_time)
    total_loc, loc_time = perf_counter(loc_query, ['OWNER', 'COLLABORATOR', 'ORGANIZATION_MEMBER'], CACHE_COMMENT_SIZE)
    formatter('LOC (cached)' if total_loc[-1] else 'LOC (no cache)', loc_time)
    commit_data, commit_time = perf_counter(commit_counter, CACHE_COMMENT_SIZE)
    formatter('commit count', commit_time)
    star_data, star_time = perf_counter(graph_repos_stars, 'stars', ['OWNER'])
    formatter('star count', star_time)
    repo_data, repo_time = perf_counter(graph_repos_stars, 'repos', ['OWNER'])
    formatter('my repositories', repo_time)
    contrib_data, contrib_time = perf_counter(graph_repos_stars, 'repos', ['OWNER', 'COLLABORATOR', 'ORGANIZATION_MEMBER'])
    formatter('contributed repos', contrib_time)
    follower_data, follower_time = perf_counter(follower_getter, USER_NAME)
    formatter('follower count', follower_time)

    loc_formatted = ['{:,}'.format(value) for value in total_loc[:-1]]

    for svg in ('dark_mode.svg', 'light_mode.svg'):
        svg_overwrite(svg, age_data, commit_data, star_data, repo_data, contrib_data, follower_data, loc_formatted)

    total_time = user_time + age_time + loc_time + commit_time + star_time + repo_time + contrib_time + follower_time
    print('Total function time:', '{:>11}'.format('%.4f' % total_time), 's')
    print('Total GitHub GraphQL API calls:', '{:>3}'.format(sum(QUERY_COUNT.values())))
