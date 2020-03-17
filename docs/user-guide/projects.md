---
   description: In this guide, we'll walk through using Ambassador Edge Stack to publish services.
---
# Publishing Services

In this guide, we'll walk you through using Ambassador Edge Stack to:

1. Deploy a simple HTTP service on the internet.
2. View build logs for your service.
3. View deploy logs for your service.
4. Make updates to your service.
3. Setup automated testing for your service.

## Before You Begin

You will need:

* A working installation of Ambassador Edge Stack...
  * With TLS configured.
  * And access to the AES admin console (https://$YOUR_HOST/edge_stack/admin/).
* A Github account.
* git

## Quick Start

1. Create a new repo from our quickstart template by going to https://github.com/datawire/project-template/generate (please note the **$OWNER** and **$REPO_NAME** you choose for later reference).
2. Go to https://$YOUR_HOST/edge_stack/admin/
3. Click on Projects -> Add
   - Fill in the name and namespace you would like to use for the Project CRD.
   - Enter **$YOUR_HOST** for the host. It is important that github can reach this host.
   - Choose a prefix where you would like to publish your project.
   - Enter **$OWNER/$REPO_NAME** for the github repo.
   - Enter a github token with **repo** scope. If you don't already have one, you can generate one by going to https://github.com/settings/tokens/new . Make sure you select the **repo** checkbox under "Select Scopes"
4. Click Save.

You will see the Project resource automatically build and deploy the code in your repo. Building the first time will take a little while. Subsequent builds will be much faster due to caching. Click on the "build" link to see your build logs in realtime.

When your build and deploy succeeds, click the URL to see your HTTP service deployed and handling requests from the internet.

## View build logs for your service.

The Projects Tab provides a complete summary of all relevant resources related to any Projects. Lets use the Projects tab to view the build logs:

1. If you haven't already, click on the "build" link next to the master deployment of your project.

You will see the output from your build. These results will live stream for any build in progress.

## View deploy logs for your service.

Seeing log output from your server is essential for debugging. You can use the Projects Tab to access the server logs for any deployment:

1. Click on the "log" link next to the master deployment of your project.

You will see the log output from your deployed server.

2. Try visiting the URL for your service in a separate window.

You will see the log output live stream.

## Making updates to your service.

Keep the Projects Tab open and visible for the rest of this section.

### Updating your service directly

Any code changes on your master branch will be automatically built and deployed. Let's make a change to see how this works:

1. Go to your git repo in your browser.
2. Click on server.js -> Edit
3. Change "Hello World!" to "Hello Master Branch!".
4. Select the "Commit directly to the `master` branch" option.
5. Click "Commit changes".

Look at your Project in the Projects Tab. You should see a new build proceeding. When that build completes you will see your change published at the url for the master deployment.

### Updating your service with a PR

If you want to test your change before putting it into producution, create a PR instead of pushing directly to master:

1. Go to your git repo in your browser.
2. Click on server.js -> Edit
3. Change "Hello World!" to "Hello Pull Requests!".
4. Select the "Create a new branch for this commit..." option.
5. Click "Propose file change".

Look at your Project in the Projects Tab. You should see a new build proceeding for your PR. When that build completes, click on its url. You will see your requested changes.

Every PR gets published at its own preview url, so you can have as many as you like and test them however you like before merging.

## Automating Tests

1. TODO

## What’s Next?

The Ambassador Edge Stack has a comprehensive range of [features](/features/) to support the requirements of any edge microservice.

To learn more about how the Ambassador Edge Stack works, along with use cases,
best practices, and more, check out the [Welcome page](/docs/) or read the
[Ambassador Story](/about/why-ambassador).

For a custom configuration, you can install the Ambassador Edge Stack [manually](/user-guide/manual-install).