# djevops

Host Django without Docker

djevops is a tool for deploying a Django web application to a Linux VPS. It runs
the application "on bare metal". That is, without any abstraction layers such as
Docker. This makes development fast and easy. djevops also solves many common
issues, such as serving the site via httpS, log inspection, error emails,
monitoring, background tasks, backups, automatic OS updates and secure defaults.

djevops grew out of Django apps I've been developing since 2014. When I found
myself copy-pasting the same (but much improved) code for deploying a Django app
for the eleventh time, I realized it is time to extract a reusable solution. My
djevops apps currently serve hundreds of thousands of users and tens of millions
of requests each month.

## Features

 * Easily run your Django app as a public website.
 * No special infrastructure required - a USD 5 per month Linux VPS is enough.
 * Fast deployments.
 * Simple debugging and development.
 * Great performance.

## Prerequisites

You need a Linux VPS running Debian 12 with SSH `root` access. This machine
needs to be reachable from the internet and have a domain name associated with
it. For example, you can rent the VPS from [Linode](https://linode.com) and buy
the domain from [DNSimple](https://dnsimple.com). Then, just create a DNS `A`
record that ties the domain to the VPS's IP.
