import io
import json
import os
import requests
import sys

# === configuration ===

# base url of the jira api
jira_base = 'https://my-organization.atlassian.net/rest/api/2'

# the authentication credentials of your jira user
jira_auth = ('my-jira-username', 'my-jira-password')

# base url of the gitlab api
gitlab_base = 'https://my-gitlab.example.com/api/v4/projects'

# your gitlab user's private token
gitlab_private_token = 'my-gitlab-token'

# the gitlab group id to create new projects under
gitlab_namespace_id = 123

# the visibility of new gitlab projects
gitlab_visibility = 'private'

# mapping of project codes to project names to migrate
projects = dict()
projects['my-project-code-1'] = 'my-project-name-1'
projects['my-project-code-2'] = 'my-project-name-2'

# === end of configuration ===

for project_code, project_name in projects.items():
    # fetch issues from jira
    issues = []
    startAt = 0
    total = 1
    while total > startAt:
        url = '%s/search?jql=project=%s+order+by+id+asc&startAt=%s' % (jira_base, project_code, startAt)
        response = requests.get(url, auth=jira_auth)
        if response.status_code != 200:
            sys.stderr.write('%s %s' % (url, response.text))
            sys.exit(1)
        response_data = json.loads(response.text)
        startAt += response_data['maxResults']
        total = response_data['total']
        issues.extend(response_data['issues'])

    # perform sanity check
    if len(issues) != total:
        sys.stderr.write('Expected %s but retrieved %s issues.\n' % (total, len(issues)))
        sys.exit(1)

    # compile project for gitlab
    data = dict()
    data['private_token'] = gitlab_private_token
    data['namespace_id'] = gitlab_namespace_id
    data['name'] = project_name
    data['path'] = project_code
    data['visibility'] = gitlab_visibility
    data['container_registry_enabled'] = 'false'
    data['issues_enabled'] = 'true'
    data['jobs_enabled'] = 'false'
    data['merge_requests_enabled'] = 'false'
    data['shared_runners_enabled'] = 'false'
    data['snippets_enabled'] = 'false'
    data['wiki_enabled'] = 'false'

    # create project in gitlab and retrieve project id
    url = gitlab_base
    response = requests.post(url, data=data)
    if response.status_code != 201:
        sys.stderr.write('%s %s' % (url, response.text))
        sys.exit(1)
    response_data = json.loads(response.text)
    gitlab_project_id = response_data['id']

    # add issues to gitlab
    for issue in issues:
        # retrieve necessary fields from jira issue
        summary = issue['fields']['summary']
        created = issue['fields']['created']
        reporter = issue['fields']['reporter']['name']
        assignee = issue['fields']['assignee']['name'] if issue['fields']['assignee'] is not None else 'None'
        description = issue['fields']['description']

        # compile issue for gitlab
        data = dict()
        data['private_token'] = gitlab_private_token
        data['title'] = summary
        data['created_at'] = created
        data['description'] = 'Reporter: %s\n\nAssignee: %s\n\n%s' % (reporter, assignee, description)

        # create issue in gitlab
        url = '%s/%s/issues' % (gitlab_base, gitlab_project_id)
        response = requests.post(url, data=data)
        if response.status_code != 201:
            sys.stderr.write('%s %s' % (url, response.text))
            sys.exit(1)
        response_data = json.loads(response.text)
        gitlab_issue_id = response_data['iid']

        # update issue status in gitlab if necessary
        if issue['fields']['status']['statusCategory']['name'] == 'Done':
            url = '%s/%s/issues/%s' % (gitlab_base, gitlab_project_id, gitlab_issue_id)
            data = dict()
            data['private_token'] = gitlab_private_token
            data['state_event'] = 'close'
            response = requests.put(url, data=data)
            if response.status_code != 200:
                sys.stderr.write('%s %s' % (url, response.text))
                sys.exit(1)

        # fetch attachments and comments from jira
        jira_issue_id = issue['id']
        url = '%s/issue/%s?fields=attachment,comment' % (jira_base, jira_issue_id)
        response = requests.get(url, auth=jira_auth)
        if response.status_code != 200:
            sys.stderr.write('%s %s' % (url, response.text))
            sys.exit(1)
        response_data = json.loads(response.text)
        attachments = response_data['fields']['attachment']
        comments = response_data['fields']['comment']['comments']

        # retrieve attachment content from jira and upload to gitlab
        for attachment in attachments:
            # retrieve attachment content from jira
            url = attachment['content']
            response = requests.get(url, auth=jira_auth)
            if response.status_code != 200:
                sys.stderr.write('%s %s' % (url, response.text))
                sys.exit(1)

            # retrieve attachment metadata
            content_type = response.headers['content-type']
            created = attachment['created']
            filename = os.path.basename(url)

            # compile attachment data for gitlab
            data = dict()
            data['private_token'] = gitlab_private_token

            # compile attachment multipart file for gitlab
            files = dict()
            files['file'] = (filename, io.BytesIO(response.content), content_type)

            # upload attachment to gitlab
            url = '%s/%s/uploads' % (gitlab_base, gitlab_project_id)
            response = requests.post(url, data=data, files=files)
            if response.status_code != 201:
                sys.stderr.write('%s %s' % (url, response.text))
                sys.exit(1)
            response_data = json.loads(response.text)
            markdown = response_data['markdown']

            # compile comment for gitlab
            data = dict()
            data['private_token'] = gitlab_private_token
            data['issue_id'] = gitlab_issue_id
            data['created_at'] = created
            data['body'] = markdown

            # create comment in gitlab
            url = '%s/%s/issues/%s/notes' % (gitlab_base, gitlab_project_id, gitlab_issue_id)
            response = requests.post(url, data=data)
            if response.status_code != 201:
                sys.stderr.write('%s %s' % (url, response.text))
                sys.exit(1)

        # add comments to gitlab
        for comment in comments:
            # retrieve necessary fields from jira comment
            author = comment['author']['name']
            created = comment['created']
            body = comment['body']

            # compile comment for gitlab
            data = dict()
            data['private_token'] = gitlab_private_token
            data['issue_id'] = gitlab_issue_id
            data['created_at'] = created
            data['body'] = 'Author: %s\n\n%s' % (author, body)

            # create comment in gitlab
            url = '%s/%s/issues/%s/notes' % (gitlab_base, gitlab_project_id, gitlab_issue_id)
            response = requests.post(url, data=data)
            if response.status_code != 201:
                sys.stderr.write('%s %s' % (url, response.text))
                sys.exit(1)
