# Copyright 2014 Google Inc. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Tool for uploading Google Code issues to an issue service.
"""

import collections
import datetime
import json
import re
import sys

import HTMLParser


class IdentityDict(dict):
  def __missing__(self, key):
    return key


def TryFormatDate(date):
  """Attempt to clean up a timestamp date."""
  try:
    if date.endswith(":"):
      date = date[:len(date) - 1]
    datetime_version = datetime.datetime.strptime(
        date, "%Y-%m-%dT%H:%M:%S.%fZ")
    return str(datetime_version)
  except ValueError as ve:
    return date


def WrapText(text, max):
  """Inserts a newline if any line of a file is > max chars.

  Note that the newline is inserted at the first whitespace
  character, so there may be lines longer than max.
  """
  char_list = list(text)
  last_linebreak = 0
  for i in range(0, len(char_list)):
    if char_list[i] == '\n' or char_list[i] == '\r':
      last_linebreak = i
    if i - last_linebreak > max and char_list[i] == ' ':
      # Replace ' ' with '\n'
      char_list.pop(i)
      char_list.insert(i, '\n')
      last_linebreak = i
  return ''.join(char_list)


class Error(Exception):
  """Base error class."""


class InvalidUserError(Error):
  """Error for an invalid user."""


class ProjectNotFoundError(Error):
  """Error for a non-existent project."""


class ServiceError(Error):
  """Error when communicating with the issue or user service."""


class UserService(object):
  """Abstract user operations.

  Handles user operations on an user API.
  """

  def IsUser(self, username):
    """Checks if the user exists.

    Args:
      username: The username to check.

    Returns:
      True if the username exists.
    """
    raise NotImplementedError()


class GoogleCodeIssue(object):
  """Google Code issue.

  Handles parsing and viewing a Google Code issue.
  """

  def __init__(self, issue, project_name, user_map):
    """Initialize the GoogleCodeIssue.

    Args:
      issue: The Google Code Issue as a dictionary.
      project_name: The name of the project the issue belongs to.
      user_map: A map from Google Code usernames to issue service names.
    """
    self._issue = issue
    self._project_name = project_name
    self._user_map = user_map

  def GetProjectName(self):
    """Returns the project name."""
    return self._project_name

  def GetUserMap(self):
    """Returns the user map."""
    return self._user_map

  def GetOwner(self):
    """Get the owner username of a Google Code issue.

    This will ALWAYS be the person requesting the issue export.
    """
    return self._user_map["user_requesting_export"]

  def GetContentUpdatedOn(self):
    """Get the date the content was last updated from a Google Code issue.

    Returns:
      The time stamp when the issue content was last updated
    """
    return self._issue["updated"]

  def GetCreatedOn(self):
    """Get the creation date from a Google Code issue.

    Returns:
      The time stamp when the issue content was created
    """
    return self._issue["published"]

  def GetId(self):
    """Get the id from a Google Code issue.

    Returns:
      The issue id
    """
    return self._issue["id"]

  def GetLabels(self):
    """Get the labels from a Google Code issue.

    Returns:
      A list of the labels of this issue.
    """
    return self._issue.get("labels", [])

  def GetKind(self):
    """Get the kind from a Google Code issue.

    Returns:
      The issue kind, if none is found defaults to 'Defect'
    """
    types = [t for t in self.GetLabels() if "Type-" in t]
    if types:
      return types[0][len("Type-"):]
    return "Defect"

  def GetPriority(self):
    """Get the priority from a Google Code issue.

    Returns:
      The issue priority, if none is found defaults to 'Medium'
    """
    priorities = [p for p in self.GetLabels() if "Priority-" in p]
    if priorities:
      return priorities[0][len("Priority-"):]
    return "Medium"

  def GetAuthor(self):
    """Get the author's username of a Google Code issue.

    Returns:
      The Google Code username that the issue is authored by or the
      repository owner if no mapping or email address exists.
    """
    if "author" not in self._issue:
      return None

    author = self._issue["author"]["name"]
    return self._user_map[author]

  def GetStatus(self):
    """Get the status from a Google Code issue.

    Returns:
      The issue status
    """
    status = self._issue["status"].lower()
    if status == "accepted":
      status = "open"
    return status

  def GetTitle(self):
    """Get the title from a Google Code issue.

    Returns:
      The issue title
    """
    return self._issue["title"]

  def GetUpdatedOn(self):
    """Get the date the issue was last updated.

    Returns:
      The time stamp when the issue was last updated
    """
    return self.GetCreatedOn()

  def _GetDescription(self):
    """Returns the raw description of the issue.

    Returns:
      The raw issue description as a comment.
    """
    return self._issue["comments"]["items"][0]

  def GetComments(self):
    """Get the list of comments for the issue (if any).

    Returns:
      The list of comments attached to the issue
    """
    # The 0th comment is the issue's description. Also, filter out
    # any deleted comments.
    comments = self._issue["comments"]["items"][1:]
    return [c for c in comments if not "deletedBy" in c]

  def IsOpen(self):
    """Check if an issue is marked as open.

    Returns:
      True if the issue was open.
    """
    return "state" in self._issue and self._issue["state"] == "open"

  def GetDescription(self):
    """Returns the Description of the issue."""
    # Just return the description of the underlying comment.
    googlecode_comment = GoogleCodeComment(self, self._GetDescription())
    return googlecode_comment.GetDescription()


class GoogleCodeComment(object):
  """Google Code Comment.

  Handles parsing and viewing a Google Code Comment.
  """

  def __init__(self, googlecode_issue, comment):
    """Initialize the GoogleCodeComment.

    Args:
      googlecode_issue: A GoogleCodeIssue instance.
      comment: The Google Code Comment as dictionary.
    """
    self._comment = comment
    self._googlecode_issue = googlecode_issue

  def GetContent(self):
    """Get the content from a Google Code comment.

    Returns:
      The issue comment
    """
    return self._comment["content"]

  def GetCreatedOn(self):
    """Get the creation date from a Google Code comment.

    Returns:
      The time stamp when the issue comment content was created
    """
    return self._comment["published"]

  def GetId(self):
    """Get the id from a Google Code comment.

    Returns:
      The issue comment id
    """
    return self._comment["id"]

  def GetLabels(self):
    """Get the labels modified with the comment."""
    if "updates" in self._comment:
      if "labels" in self._comment["updates"]:
        return self._comment["updates"]["labels"]
    return []

  def GetIssue(self):
    """Get the GoogleCodeIssue this comment belongs to.

    Returns:
      The issue id
    """
    return self._googlecode_issue

  def GetUpdatedOn(self):
    """Get the date the issue comment content was last updated.

    Returns:
      The time stamp when the issue comment content was last updated
    """
    return self.GetCreatedOn()

  def GetAuthor(self):
    """Get the author's username of a Google Code issue comment.

    Returns:
      The Google Code username that the issue comment is authored by or the
      repository owner if no mapping or email address exists.
    """
    if "author" not in self._comment:
      return None

    author = self._comment["author"]["name"]
    return self.GetIssue().GetUserMap()[author]

  def GetDescription(self):
    """Returns the Description of the comment."""
    author = self.GetAuthor()
    comment_date = self.GetCreatedOn()
    comment_text = self.GetContent()

    if not comment_text:
      comment_text = "(No text was entered with this change)"

    # Google Takeout includes expected HTML characters such as &gt and &aacute.
    html_parser = HTMLParser.HTMLParser()
    comment_text = html_parser.unescape(comment_text)

    # Remove <b> tags, which Codesite automatically includes if issue body is
    # based on a prompt.
    comment_text = comment_text.replace("<b>", "")
    comment_text = comment_text.replace("</b>", "")
    comment_text = WrapText(comment_text, 82)  # In case it was already wrapped...

    body = "```\n" + comment_text + "\n```"

    footer = "\n\nOriginal issue reported on code.google.com by `%s` on %s" % (
        author, TryFormatDate(comment_date))

    # Add label adjustments.
    if self.GetLabels():
      labels_added = []
      labels_removed = []
      for label in self.GetLabels():
        if label.startswith("-"):
          labels_removed.append(label[1:])
        else:
          labels_added.append(label)

      footer += "\n"
      if labels_added:
        footer += "- **Labels added**: %s\n" % (", ".join(labels_added))
      if labels_removed:
        footer += "- **Labels removed**: %s\n" % (", ".join(labels_removed))

    # Add references to attachments as appropriate.
    attachmentLines = []
    for attachment in self._comment["attachments"] if "attachments" in self._comment else []:
      if "isDeleted" in attachment:
        # Deleted attachments won't be found on the issue mirror.
        continue

      link = "https://storage.googleapis.com/google-code-attachments/%s/issue-%d/comment-%d/%s" % (
          self.GetIssue().GetProjectName(), self.GetIssue().GetId(),
          self.GetId(), attachment["fileName"])

      def has_extension(extension):
        return attachment["fileName"].lower().endswith(extension)

      is_image_attachment = False
      for extension in [".png", ".jpg", ".jpeg", ".bmp", ".tif", ".gif"]:
        is_image_attachment |= has_extension(".png")

      if is_image_attachment:
        line = " * *Attachment: %s<br>![%s](%s)*" % (
            attachment["fileName"], attachment["fileName"], link)
      else:
        line = " * *Attachment: [%s](%s)*" % (attachment["fileName"], link)
      attachmentLines.append(line)

    if len(attachmentLines) > 0:
      footer += "\n<hr>\n" + "\n".join(attachmentLines)

    # Return the data to send to generate the comment.
    return body + footer


class IssueService(object):
  """Abstract issue operations.

  Handles creating and updating issues and comments on an user API.
  """

  def GetIssues(self, state="open"):
    """Gets all of the issue for the repository.

    Args:
      state: The state of the repository can be either 'open' or 'closed'.

    Returns:
      The list of all of the issues for the given repository.

    Raises:
      IOError: An error occurred accessing previously created issues.
    """
    raise NotImplementedError()

  def CreateIssue(self, googlecode_issue):
    """Creates an issue.

    Args:
      googlecode_issue: An instance of GoogleCodeIssue

    Returns:
      The issue number of the new issue.

    Raises:
      ServiceError: An error occurred creating the issue.
    """
    raise NotImplementedError()

  def CloseIssue(self, issue_number):
    """Closes an issue.

    Args:
      issue_number: The issue number.
    """
    raise NotImplementedError()

  def CreateComment(self, issue_number, source_issue_id,
                    googlecode_comment, project_name):
    """Creates a comment on an issue.

    Args:
      issue_number: The issue number.
      source_issue_id: The Google Code issue id.
      googlecode_comment: An instance of GoogleCodeComment
      project_name: The Google Code project name.
    """
    raise NotImplementedError()


def LoadIssueData(issue_file_path, project_name):
  """Loads issue data from a file.

  Args:
    issue_file_path: path to the file to load
    project_name: name of the project to load

  Returns:
    Issue data as a list of dictionaries.

  Raises:
    ProjectNotFoundError: the project_name was not found in the file.
  """
  with open(issue_file_path) as user_file:
    user_data = json.load(user_file)
    user_projects = user_data["projects"]

    for project in user_projects:
      if project_name == project["name"]:
        return project["issues"]["items"]

  raise ProjectNotFoundError("Project %s not found" % project_name)


def LoadUserData(user_file_path, user_service):
  """Loads user data from a file. If not present, the user name will
  just return whatever is passed to it.

  Args:
    user_file_path: path to the file to load
    user_service: an instance of UserService
  """
  identity_dict = IdentityDict()
  if not user_file_path:
    return identity_dict

  with open(user_file_path) as user_data:
    user_json = user_data.read()

  user_map = json.loads(user_json)["users"]
  for username in user_map.values():
    if not user_service.IsUser(username):
      raise InvalidUserError("%s is not a User" % username)

  result.update(user_map)
  return result


class IssueExporter(object):
  """Issue Migration.

  Handles the uploading issues from Google Code to an issue service.
  """

  def __init__(self, issue_service, user_service, issue_json_data,
               project_name, user_map):
    """Initialize the IssueExporter.

    Args:
      issue_service: An instance of IssueService.
      user_service: An instance of UserService.
      project_name: The name of the project to export to.
      issue_json_data: A data object of issues from Google Code.
      user_map: A map from user email addresses to service usernames.
    """
    self._issue_service = issue_service
    self._user_service = user_service
    self._issue_json_data = issue_json_data
    self._project_name = project_name
    self._user_map = user_map

    # Mapping from issue ID to the issue's metadata. This is used to verify
    # consistency with an previous attempts at exporting issues.
    self._previously_created_issues = {}

    self._issue_total = 0
    self._issue_number = 0
    self._comment_number = 0
    self._comment_total = 0
    self._skipped_issues = 0

  def Init(self):
    """Initialize the needed variables."""
    self._GetAllPreviousIssues()

  def _GetAllPreviousIssues(self):
    """Gets all previously uploaded issues."""
    print "Getting any previously added issues..."
    open_issues = self._issue_service.GetIssues("open")
    closed_issues = self._issue_service.GetIssues("closed")
    issues = open_issues + closed_issues
    for issue in issues:
      # Yes, GitHub's issues API has both ID and Number, and they are
      # the opposite of what you think they are.
      issue["number"] not in self._previously_created_issues or die(
          "GitHub returned multiple issues with the same ID?")
      self._previously_created_issues[issue["number"]] = {
          "title": issue["title"],
          "comment_count": issue["comments"],
        }

  def _UpdateProgressBar(self):
    """Update issue count 'feed'.

    This displays the current status of the script to the user.
    """
    feed_string = ("\rIssue: %d/%d -> Comment: %d/%d        " %
                   (self._issue_number, self._issue_total,
                    self._comment_number, self._comment_total))
    sys.stdout.write(feed_string)
    sys.stdout.flush()

  def _CreateIssue(self, googlecode_issue):
    """Converts an issue from Google Code to an issue service.

    This will take the Google Code issue and create a corresponding issue on
    the issue service.  If the issue on Google Code was closed it will also
    be closed on the issue service.

    Args:
      googlecode_issue: An instance of GoogleCodeIssue

    Returns:
      The issue number assigned by the service.
    """
    return self._issue_service.CreateIssue(googlecode_issue)

  def _CreateComments(self, comments, issue_number, googlecode_issue):
    """Converts a list of issue comment from Google Code to an issue service.

    This will take a list of Google Code issue comments and create
    corresponding comments on an issue service for the given issue number.

    Args:
      comments: A list of comments (each comment is just a string).
      issue_number: The issue number.
      source_issue_id: The Google Code issue id.
    """
    self._comment_total = len(comments)
    self._comment_number = 0

    for comment in comments:
      googlecode_comment = GoogleCodeComment(googlecode_issue, comment)
      self._comment_number += 1
      self._UpdateProgressBar()
      self._issue_service.CreateComment(issue_number,
                                        googlecode_issue.GetId(),
                                        googlecode_comment,
                                        self._project_name)

  def Start(self):
    """The primary function that runs this script.

    This will traverse the issues and attempt to create each issue and its
    comments.
    """
    print "Starting issue export for '%s'" % (self._project_name)

    DELETED_ISSUE_PLACEHOLDER = GoogleCodeIssue(
        {
            "title": "[Issue Deleted]",
            "id": -1,
            "published": "NA",
            "author": "NA",
            "comments": {
                "items": [{
                    "id": 0,
                    "author": {
                        "name": "NA",
                    },
                    "content": "...",
                    "published": "NA"}],
            },
        },
        self._project_name, self._user_map)

    # If there are existing issues, then confirm they exactly match the Google
    # Code issues. Otherwise issue IDs will not match and/or there may be
    # missing data.
    self._AssertInGoodState()

    self._issue_total = len(self._issue_json_data)
    self._issue_number = 0
    self._skipped_issues = 0

    # ID of the last issue that was posted to the external service. Should
    # be one less than the current issue to import.
    last_issue_id = 0

    for issue in self._issue_json_data:
      googlecode_issue = GoogleCodeIssue(
          issue, self._project_name, self._user_map)

      self._issue_number += 1
      self._UpdateProgressBar()

      if googlecode_issue.GetId() in self._previously_created_issues:
        self._skipped_issues += 1
        last_issue_id = googlecode_issue.GetId()
        continue

      # If the Google Code JSON dump skipped any issues (e.g. they were deleted)
      # then create placeholder issues so the ID count matches.
      while int(googlecode_issue.GetId()) > int(last_issue_id) + 1:
        last_issue_id = self._CreateIssue(DELETED_ISSUE_PLACEHOLDER)
        print "\nCreating deleted issue placeholder for #%s" % (last_issue_id)
        self._issue_service.CloseIssue(last_issue_id)

      # Create the issue on the remote site. Verify that the issue number
      # matches. Otherwise the counts will be off. e.g. a new GitHub issue
      # was created during the export, so Google Code issue 100 refers to
      # GitHub issue 101, and so on.
      last_issue_id = self._CreateIssue(googlecode_issue)
      if last_issue_id < 0:
        continue
      if int(last_issue_id) != int(googlecode_issue.GetId()):
        error_message = (
            "Google Code and GitHub issue numbers mismatch. Created\n"
            "Google Code issue #%s, but it was saved as issue #%s." % (
                googlecode_issue.GetId(), last_issue_id))
        raise RuntimeError(error_message)

      comments = googlecode_issue.GetComments()
      self._CreateComments(comments, last_issue_id, googlecode_issue)

      if not googlecode_issue.IsOpen():
        self._issue_service.CloseIssue(last_issue_id)

    if self._skipped_issues > 0:
      print ("\nSkipped %d/%d issue previously uploaded." %
             (self._skipped_issues, self._issue_total))

  def _AssertInGoodState(self):
    """Checks if the last issue exported is sound, otherwise raises an error.

    Checks the existing issues that have been exported and confirms that it
    matches the issue on Google Code. (Both Title and ID match.) It then
    confirms that it has all of the expected comments, adding any missing ones
    as necessary.
    """
    if len(self._previously_created_issues) == 0:
      return

    print ("Existing issues detected for the repo. Likely due to a previous\n"
           "    run being aborted or killed. Checking consistency...")

    # Get the last exported issue, and its dual on Google Code.
    last_gh_issue_id = -1
    for id in self._previously_created_issues:
      if id > last_gh_issue_id:
        last_gh_issue_id = id
        last_gh_issue = self._previously_created_issues[last_gh_issue_id]

    last_gc_issue = None
    for issue in self._issue_json_data:
      if int(issue["id"]) == int(last_gh_issue_id) and (
          issue["title"] == last_gh_issue["title"]):
        last_gc_issue = GoogleCodeIssue(issue,
                                        self._project_name,
                                        self._user_map)
        break

    if last_gc_issue is None:
      raise RuntimeError(
          "Unable to find Google Code issue #%s '%s'.\n"
          "    Were issues added to GitHub since last export attempt?" % (
              last_gh_issue_id, last_gh_issue["title"]))

    print "Last issue (#%s) matches. Checking comments..." % (last_gh_issue_id)

    # Check comments. Add any missing ones as needed.
    num_gc_issue_comments = len(last_gc_issue.GetComments())
    if last_gh_issue["comment_count"] != num_gc_issue_comments:
      print "GitHub issue has fewer comments than Google Code's. Fixing..."
      for idx in range(last_gh_issue["comment_count"], num_gc_issue_comments):
        comment = last_gc_issue.GetComments()[idx]
        googlecode_comment = GoogleCodeComment(last_gc_issue, comment)
        # issue_number == source_issue_id
        self._issue_service.CreateComment(
            int(last_gc_issue.GetId()), int(last_gc_issue.GetId()),
            googlecode_comment, self._project_name)
        print "  Added comment #%s." % (idx + 1)

    print "Done! Issue tracker now in expected state. Ready for more exports."
