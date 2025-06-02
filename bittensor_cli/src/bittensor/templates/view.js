/* ===================== Global Variables ===================== */
const root_symbol_html = '&#x03C4;';
let verboseNumbers = false;

/* ===================== Clipboard Functions ===================== */
/**
* Copies text to clipboard and shows visual feedback
* @param {string} text The text to copy
* @param {HTMLElement} element Optional element to show feedback on
*/
function copyToClipboard(text, element) {
    navigator.clipboard.writeText(text)
        .then(() => {
            const targetElement = element || (event && event.target);

            if (targetElement) {
                const copyIndicator = targetElement.querySelector('.copy-indicator');

                if (copyIndicator) {
                    const originalText = copyIndicator.textContent;
                    copyIndicator.textContent = 'Copied!';
                    copyIndicator.style.color = '#FF9900';

                    setTimeout(() => {
                        copyIndicator.textContent = originalText;
                        copyIndicator.style.color = '';
                    }, 1000);
                } else {
                    const originalText = targetElement.textContent;
                    targetElement.textContent = 'Copied!';
                    targetElement.style.color = '#FF9900';

                    setTimeout(() => {
                        targetElement.textContent = originalText;
                        targetElement.style.color = '';
                    }, 1000);
                }
            }
        })
        .catch(err => {
            console.error('Failed to copy:', err);
        });
}


/* ===================== Initialization and DOMContentLoaded Handler ===================== */
document.addEventListener('DOMContentLoaded', function() {
    try {
        const initialDataElement = document.getElementById('initial-data');
        if (!initialDataElement) {
            throw new Error('Initial data element (#initial-data) not found.');
        }
        window.initialData = {
            wallet_info: JSON.parse(initialDataElement.getAttribute('data-wallet-info')),
            subnets: JSON.parse(initialDataElement.getAttribute('data-subnets'))
        };
    } catch (error) {
        console.error('Error loading initial data:', error);
    }

    // Return to the main list of subnets.
    const backButton = document.querySelector('.back-button');
    if (backButton) {
        backButton.addEventListener('click', function() {
            // First check if neuron details are visible and close them if needed
            const neuronDetails = document.getElementById('neuron-detail-container');
            if (neuronDetails && neuronDetails.style.display !== 'none') {
                closeNeuronDetails();
                return; // Stop here, don't go back to main page yet
            }

            // Otherwise go back to main subnet list
            document.getElementById('main-content').style.display = 'block';
            document.getElementById('subnet-page').style.display = 'none';
        });
    }


    // Splash screen logic
    const splash = document.getElementById('splash-screen');
    const mainContent = document.getElementById('main-content');
    mainContent.style.display = 'none';

    setTimeout(() => {
        splash.classList.add('fade-out');
        splash.addEventListener('transitionend', () => {
            splash.style.display = 'none';
            mainContent.style.display = 'block';
        }, { once: true });
    }, 2000);

    initializeFormattedNumbers();

    // Keep main page's "verbose" checkbox and the Subnet page's "verbose" checkbox in sync
    const mainVerboseCheckbox = document.getElementById('show-verbose');
    const subnetVerboseCheckbox = document.getElementById('verbose-toggle');
    if (mainVerboseCheckbox && subnetVerboseCheckbox) {
        mainVerboseCheckbox.addEventListener('change', function() {
            subnetVerboseCheckbox.checked = this.checked;
            toggleVerboseNumbers();
        });
        subnetVerboseCheckbox.addEventListener('change', function() {
            mainVerboseCheckbox.checked = this.checked;
            toggleVerboseNumbers();
        });
    }

    // Initialize tile view as default
    const tilesContainer = document.getElementById('subnet-tiles-container');
    const tableContainer = document.querySelector('.subnets-table-container');

    // Generate and show tiles
    generateSubnetTiles();
    tilesContainer.style.display = 'flex';
    tableContainer.style.display = 'none';
});

/* ===================== Main Page Functions ===================== */
/**
* Sort the main Subnets table by the specified column index.
* Toggles ascending/descending on each click.
* @param {number} columnIndex Index of the column to sort.
*/
function sortMainTable(columnIndex) {
    const table = document.querySelector('.subnets-table');
    const headers = table.querySelectorAll('th');
    const header = headers[columnIndex];

    // Determine new sort direction
    let isDescending = header.getAttribute('data-sort') !== 'desc';

    // Clear sort markers on all columns, then set the new one
    headers.forEach(th => { th.removeAttribute('data-sort'); });
    header.setAttribute('data-sort', isDescending ? 'desc' : 'asc');

    // Sort rows based on numeric value (or netuid in col 0)
    const tbody = table.querySelector('tbody');
    const rows = Array.from(tbody.querySelectorAll('tr'));
    rows.sort((rowA, rowB) => {
        const cellA = rowA.cells[columnIndex];
        const cellB = rowB.cells[columnIndex];

        // Special handling for the first column with netuid in data-value
        if (columnIndex === 0) {
            const netuidA = parseInt(cellA.getAttribute('data-value'), 10);
            const netuidB = parseInt(cellB.getAttribute('data-value'), 10);
            return isDescending ? (netuidB - netuidA) : (netuidA - netuidB);
        }

        // Otherwise parse float from data-value
        const valueA = parseFloat(cellA.getAttribute('data-value')) || 0;
        const valueB = parseFloat(cellB.getAttribute('data-value')) || 0;
        return isDescending ? (valueB - valueA) : (valueA - valueB);
    });

    // Re-inject rows in sorted order
    tbody.innerHTML = '';
    rows.forEach(row => tbody.appendChild(row));
}

/**
* Filters the main Subnets table rows based on user search and "Show Only Staked" checkbox.
*/
function filterSubnets() {
    const searchText = document.getElementById('subnet-search').value.toLowerCase();
    const showStaked = document.getElementById('show-staked').checked;
    const showTiles = document.getElementById('show-tiles').checked;

    // Filter table rows
    const rows = document.querySelectorAll('.subnet-row');
    rows.forEach(row => {
        const name = row.querySelector('.subnet-name').textContent.toLowerCase();
        const stakeStatus = row.querySelector('.stake-status').textContent; // "Staked" or "Not Staked"

        let isVisible = name.includes(searchText);
        if (showStaked) {
            // If "Show only Staked" is checked, the row must have "Staked" to be visible
            isVisible = isVisible && (stakeStatus === 'Staked');
        }
        row.style.display = isVisible ? '' : 'none';
    });

    // Filter tiles if they're being shown
    if (showTiles) {
        const tiles = document.querySelectorAll('.subnet-tile');
        tiles.forEach(tile => {
            const name = tile.querySelector('.tile-name').textContent.toLowerCase();
            const netuid = tile.querySelector('.tile-netuid').textContent;
            const isStaked = tile.classList.contains('staked');

            let isVisible = name.includes(searchText) || netuid.includes(searchText);
            if (showStaked) {
                isVisible = isVisible && isStaked;
            }
            tile.style.display = isVisible ? '' : 'none';
        });
    }
}


/* ===================== Subnet Detail Page Functions ===================== */
/**
* Displays the Subnet page (detailed view) for the selected netuid.
* Hides the main content and populates all the metrics / stakes / network table.
* @param {number} netuid The netuid of the subnet to show in detail.
*/
function showSubnetPage(netuid) {
    try {
        window.currentSubnet = netuid;
        window.scrollTo(0, 0);

        const subnet = window.initialData.subnets.find(s => s.netuid === parseInt(netuid, 10));
        if (!subnet) {
            throw new Error(`Subnet not found for netuid: ${netuid}`);
        }
        window.currentSubnetSymbol = subnet.symbol;

        // Insert the "metagraph" table beneath the "stakes" table in the hidden container
        const networkTableHTML = `
            <div class="network-table-container" style="display: none;">
                <div class="network-search-container">
                    <input type="text" class="network-search" placeholder="Search for name, hotkey, or coldkey ss58..."
                        oninput="filterNetworkTable(this.value)" id="network-search">
                </div>
                <table class="network-table">
                    <thead>
                        <tr>
                            <th>Name</th>
                            <th>Stake Weight</th>
                            <th>Stake <span style="color: #FF9900">${subnet.symbol}</span></th>
                            <th>Stake <span style="color: #FF9900">${root_symbol_html}</span></th>
                            <th>Dividends</th>
                            <th>Incentive</th>
                            <th>Emissions <span class="per-day">/day</span></th>
                            <th>Hotkey</th>
                            <th>Coldkey</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${generateNetworkTableRows(subnet.metagraph_info)}
                    </tbody>
                </table>
            </div>
        `;

        // Show/hide main content vs. subnet detail
        document.getElementById('main-content').style.display = 'none';
        document.getElementById('subnet-page').style.display = 'block';

        document.querySelector('#subnet-title').textContent = `${subnet.netuid} - ${subnet.name}`;
        document.querySelector('#subnet-price').innerHTML      = formatNumber(subnet.price, subnet.symbol);
        document.querySelector('#subnet-market-cap').innerHTML = formatNumber(subnet.market_cap, root_symbol_html);
        document.querySelector('#subnet-total-stake').innerHTML= formatNumber(subnet.total_stake, subnet.symbol);
        document.querySelector('#subnet-emission').innerHTML   = formatNumber(subnet.emission, root_symbol_html);


        const metagraphInfo = subnet.metagraph_info;
        document.querySelector('#network-alpha-in').innerHTML  = formatNumber(metagraphInfo.alpha_in, subnet.symbol);
        document.querySelector('#network-tau-in').innerHTML    = formatNumber(metagraphInfo.tao_in, root_symbol_html);
        document.querySelector('#network-moving-price').innerHTML = formatNumber(metagraphInfo.moving_price, subnet.symbol);

        // Registration status
        const registrationElement = document.querySelector('#network-registration');
        registrationElement.textContent = metagraphInfo.registration_allowed ? 'Open' : 'Closed';
        registrationElement.classList.toggle('closed', !metagraphInfo.registration_allowed);

        // Commit-Reveal Weight status
        const crElement = document.querySelector('#network-cr');
        crElement.textContent = metagraphInfo.commit_reveal_weights_enabled ? 'Enabled' : 'Disabled';
        crElement.classList.toggle('disabled', !metagraphInfo.commit_reveal_weights_enabled);

        // Blocks since last step, out of tempo
        document.querySelector('#network-blocks-since-step').innerHTML =
            `${metagraphInfo.blocks_since_last_step}/${metagraphInfo.tempo}`;

        // Number of neurons vs. max
        document.querySelector('#network-neurons').innerHTML =
            `${metagraphInfo.num_uids}/${metagraphInfo.max_uids}`;

        // Update "Your Stakes" table
        const stakesTableBody = document.querySelector('#stakes-table-body');
        stakesTableBody.innerHTML = '';
        if (subnet.your_stakes && subnet.your_stakes.length > 0) {
            subnet.your_stakes.forEach(stake => {
                const row = document.createElement('tr');
                row.innerHTML = `
                    <td class="hotkey-cell">
                        <div class="hotkey-container">
                            <span class="hotkey-identity" style="color: #FF9900">${stake.hotkey_identity}</span>
                            <!-- Remove the unused event param -->
                            <span class="copy-button" onclick="copyToClipboard('${stake.hotkey}')">copy</span>
                        </div>
                    </td>
                    <td>${formatNumber(stake.amount, subnet.symbol)}</td>
                    <td>${formatNumber(stake.ideal_value, root_symbol_html)}</td>
                    <td>${formatNumber(stake.slippage_value, root_symbol_html)} (${stake.slippage_percentage.toFixed(2)}%)</td>
                    <td>${formatNumber(stake.emission, subnet.symbol + '/day')}</td>
                    <td>${formatNumber(stake.tao_emission, root_symbol_html + '/day')}</td>
                    <td class="registered-cell">
                        <span class="${stake.is_registered ? 'registered-yes' : 'registered-no'}">
                            ${stake.is_registered ? 'Yes' : 'No'}
                        </span>
                    </td>
                    <td class="actions-cell">
                        <button class="manage-button">Coming soon</button>
                    </td>
                `;
                stakesTableBody.appendChild(row);
            });
        } else {
            // If no user stake in this subnet
            stakesTableBody.innerHTML = `
                <tr class="no-stakes-row">
                    <td colspan="8">No stakes found for this subnet</td>
                </tr>
            `;
        }

        // Remove any previously injected network table then add the new one
        const existingNetworkTable = document.querySelector('.network-table-container');
        if (existingNetworkTable) {
            existingNetworkTable.remove();
        }
        document.querySelector('.stakes-table-container').insertAdjacentHTML('afterend', networkTableHTML);

        // Format the new numbers
        initializeFormattedNumbers();

        // Initialize connectivity visualization (the dots / lines "animation")
        setTimeout(() => { initNetworkVisualization(); }, 100);

        // Toggle whether we are showing the "Your Stakes" or "Metagraph" table
        toggleStakeView();

        // Initialize sorting on newly injected table columns
        initializeSorting();

        // Auto-sort by Stake descending on the network table for convenience
        setTimeout(() => {
            const networkTable = document.querySelector('.network-table');
            if (networkTable) {
                const stakeColumn = networkTable.querySelector('th:nth-child(2)');
                if (stakeColumn) {
                    sortTable(networkTable, 1, stakeColumn, true);
                    stakeColumn.setAttribute('data-sort', 'desc');
                }
            }
        }, 100);

        console.log('Subnet page updated successfully');
    } catch (error) {
        console.error('Error updating subnet page:', error);
    }
}

/**
* Generates the rows for the "Neurons" table (shown when the user unchecks "Show Stakes").
* Each row, when clicked, calls showNeuronDetails(i).
* @param {Object} metagraphInfo The "metagraph_info" of the subnet that holds hotkeys, etc.
*/
function generateNetworkTableRows(metagraphInfo) {
    const rows = [];
    console.log('Generating network table rows with data:', metagraphInfo);

    for (let i = 0; i < metagraphInfo.hotkeys.length; i++) {
        // Subnet symbol is used to show token vs. root stake
        const subnet = window.initialData.subnets.find(s => s.netuid === window.currentSubnet);
        const subnetSymbol = subnet ? subnet.symbol : '';

        // Possibly show hotkey/coldkey truncated for readability
        const truncatedHotkey = truncateAddress(metagraphInfo.hotkeys[i]);
        const truncatedColdkey = truncateAddress(metagraphInfo.coldkeys[i]);
        const identityName = metagraphInfo.updated_identities[i] || '~';

        // Root stake is being scaled by 0.18 arbitrarily here
        const adjustedRootStake = metagraphInfo.tao_stake[i] * 0.18;

        rows.push(`
            <tr onclick="showNeuronDetails(${i})">
                <td class="identity-cell">${identityName}</td>
                <td data-value="${metagraphInfo.total_stake[i]}">
                    <span class="formatted-number" data-value="${metagraphInfo.total_stake[i]}" data-symbol="${subnetSymbol}"></span>
                </td>
                <td data-value="${metagraphInfo.alpha_stake[i]}">
                    <span class="formatted-number" data-value="${metagraphInfo.alpha_stake[i]}" data-symbol="${subnetSymbol}"></span>
                </td>
                <td data-value="${adjustedRootStake}">
                    <span class="formatted-number" data-value="${adjustedRootStake}" data-symbol="${root_symbol_html}"></span>
                </td>
                <td data-value="${metagraphInfo.dividends[i]}">
                    <span class="formatted-number" data-value="${metagraphInfo.dividends[i]}" data-symbol=""></span>
                </td>
                <td data-value="${metagraphInfo.incentives[i]}">
                    <span class="formatted-number" data-value="${metagraphInfo.incentives[i]}" data-symbol=""></span>
                </td>
                <td data-value="${metagraphInfo.emission[i]}">
                    <span class="formatted-number" data-value="${metagraphInfo.emission[i]}" data-symbol="${subnetSymbol}"></span>
                </td>
                <td class="address-cell">
                    <div class="hotkey-container" data-full-address="${metagraphInfo.hotkeys[i]}">
                        <span class="truncated-address">${truncatedHotkey}</span>
                        <span class="copy-button" onclick="event.stopPropagation(); copyToClipboard('${metagraphInfo.hotkeys[i]}')">copy</span>
                    </div>
                </td>
                <td class="address-cell">
                    <div class="hotkey-container" data-full-address="${metagraphInfo.coldkeys[i]}">
                        <span class="truncated-address">${truncatedColdkey}</span>
                        <span class="copy-button" onclick="event.stopPropagation(); copyToClipboard('${metagraphInfo.coldkeys[i]}')">copy</span>
                    </div>
                </td>
            </tr>
        `);
    }
    return rows.join('');
}

/**
* Handles toggling between the "Your Stakes" view and the "Neurons" view on the Subnet page.
* The "Show Stakes" checkbox (#stake-toggle) controls which table is visible.
*/
function toggleStakeView() {
    const showStakes = document.getElementById('stake-toggle').checked;
    const stakesTable = document.querySelector('.stakes-table-container');
    const networkTable = document.querySelector('.network-table-container');
    const sectionHeader = document.querySelector('.view-header');
    const neuronDetails = document.getElementById('neuron-detail-container');
    const addStakeButton = document.querySelector('.add-stake-button');
    const exportCsvButton = document.querySelector('.export-csv-button');
    const stakesHeader = document.querySelector('.stakes-header');

    // First, close neuron details if they're open
    if (neuronDetails && neuronDetails.style.display !== 'none') {
        neuronDetails.style.display = 'none';
    }

    // Always show the section header and stakes header when toggling views
    if (sectionHeader) sectionHeader.style.display = 'block';
    if (stakesHeader) stakesHeader.style.display = 'flex';

    if (showStakes) {
        // Show the Stakes table, hide the Neurons table
        stakesTable.style.display = 'block';
        networkTable.style.display = 'none';
        sectionHeader.textContent = 'Your Stakes';
        if (addStakeButton) {
            addStakeButton.style.display = 'none';
        }
        if (exportCsvButton) {
            exportCsvButton.style.display = 'none';
        }
    } else {
        // Show the Neurons table, hide the Stakes table
        stakesTable.style.display = 'none';
        networkTable.style.display = 'block';
        sectionHeader.textContent = 'Metagraph';
        if (addStakeButton) {
            addStakeButton.style.display = 'block';
        }
        if (exportCsvButton) {
            exportCsvButton.style.display = 'block';
        }
    }
}

/**
* Called when you click a row in the "Neurons" table, to display more detail about that neuron.
* This hides the "Neurons" table and shows the #neuron-detail-container.
* @param {number} rowIndex The index of the neuron in the arrays (hotkeys, coldkeys, etc.)
*/
function showNeuronDetails(rowIndex) {
    try {
        // Hide the network table & stakes table
        const networkTable = document.querySelector('.network-table-container');
        if (networkTable) networkTable.style.display = 'none';
        const stakesTable = document.querySelector('.stakes-table-container');
        if (stakesTable) stakesTable.style.display = 'none';

        // Hide the stakes header with the action buttons
        const stakesHeader = document.querySelector('.stakes-header');
        if (stakesHeader) stakesHeader.style.display = 'none';

        // Hide the view header that says "Neurons"
        const viewHeader = document.querySelector('.view-header');
        if (viewHeader) viewHeader.style.display = 'none';

        // Show the neuron detail panel
        const detailContainer = document.getElementById('neuron-detail-container');
        if (detailContainer) detailContainer.style.display = 'block';

        // Pull out the current subnet
        const subnet = window.initialData.subnets.find(s => s.netuid === window.currentSubnet);
        if (!subnet) {
            console.error('No subnet data for netuid:', window.currentSubnet);
            return;
        }

        const metagraphInfo = subnet.metagraph_info;
        const subnetSymbol = subnet.symbol || '';

        // Pull axon data, for IP info
        const axonData = metagraphInfo.processed_axons ? metagraphInfo.processed_axons[rowIndex] : null;
        let ipInfoString;

        // Update IP info card - hide header if IP info is present
        const ipInfoCard = document.getElementById('neuron-ipinfo').closest('.metric-card');
        if (axonData && axonData.ip !== 'N/A') {
            // If we have valid IP info, hide the "IP Info" label
            if (ipInfoCard && ipInfoCard.querySelector('.metric-label')) {
                ipInfoCard.querySelector('.metric-label').style.display = 'none';
            }
            // Format IP info with green labels
            ipInfoString = `<span style="color: #FF9900">IP:</span> ${axonData.ip}<br>` +
                        `<span style="color: #FF9900">Port:</span> ${axonData.port}<br>` +
                        `<span style="color: #FF9900">Type:</span> ${axonData.ip_type}`;
    } else {
            // If no IP info, show the label
            if (ipInfoCard && ipInfoCard.querySelector('.metric-label')) {
                ipInfoCard.querySelector('.metric-label').style.display = 'block';
            }
            ipInfoString = '<span style="color: #ff4444; font-size: 1.2em;">N/A</span>';
        }

        // Basic identity and hotkey/coldkey info
        const name      = metagraphInfo.updated_identities[rowIndex] || '~';
        const hotkey    = metagraphInfo.hotkeys[rowIndex];
        const coldkey   = metagraphInfo.coldkeys[rowIndex];
        const rank      = metagraphInfo.rank ? metagraphInfo.rank[rowIndex] : 0;
        const trust     = metagraphInfo.trust ? metagraphInfo.trust[rowIndex] : 0;
        const pruning   = metagraphInfo.pruning_score ? metagraphInfo.pruning_score[rowIndex] : 0;
        const vPermit   = metagraphInfo.validator_permit ? metagraphInfo.validator_permit[rowIndex] : false;
        const lastUpd   = metagraphInfo.last_update ? metagraphInfo.last_update[rowIndex] : 0;
        const consensus = metagraphInfo.consensus ? metagraphInfo.consensus[rowIndex] : 0;
        const regBlock  = metagraphInfo.block_at_registration ? metagraphInfo.block_at_registration[rowIndex] : 0;
        const active    = metagraphInfo.active ? metagraphInfo.active[rowIndex] : false;

        // Update UI fields
        document.getElementById('neuron-name').textContent = name;
        document.getElementById('neuron-name').style.color = '#FF9900';

        document.getElementById('neuron-hotkey').textContent = hotkey;
        document.getElementById('neuron-coldkey').textContent = coldkey;
        document.getElementById('neuron-trust').textContent = trust.toFixed(4);
        document.getElementById('neuron-pruning-score').textContent = pruning.toFixed(4);

        // Validator
        const validatorElem = document.getElementById('neuron-validator-permit');
        if (vPermit) {
            validatorElem.style.color = '#2ECC71';
            validatorElem.textContent = 'True';
        } else {
            validatorElem.style.color = '#ff4444';
            validatorElem.textContent = 'False';
        }

        document.getElementById('neuron-last-update').textContent = lastUpd;
        document.getElementById('neuron-consensus').textContent = consensus.toFixed(4);
        document.getElementById('neuron-reg-block').textContent = regBlock;
        document.getElementById('neuron-ipinfo').innerHTML = ipInfoString;

        const activeElem = document.getElementById('neuron-active');
        if (active) {
            activeElem.style.color = '#2ECC71';
            activeElem.textContent = 'Yes';
        } else {
            activeElem.style.color = '#ff4444';
            activeElem.textContent = 'No';
        }

        // Add stake data ("total_stake", "alpha_stake", "tao_stake")
        document.getElementById('neuron-stake-total').setAttribute(
            'data-value', metagraphInfo.total_stake[rowIndex]
        );
        document.getElementById('neuron-stake-total').setAttribute(
            'data-symbol', subnetSymbol
        );

        document.getElementById('neuron-stake-token').setAttribute(
            'data-value', metagraphInfo.alpha_stake[rowIndex]
        );
        document.getElementById('neuron-stake-token').setAttribute(
            'data-symbol', subnetSymbol
        );

        // Multiply tao_stake by 0.18
        const originalStakeRoot = metagraphInfo.tao_stake[rowIndex];
        const calculatedStakeRoot = originalStakeRoot * 0.18;

        document.getElementById('neuron-stake-root').setAttribute(
            'data-value', calculatedStakeRoot
        );
        document.getElementById('neuron-stake-root').setAttribute(
            'data-symbol', root_symbol_html
        );
        // Also set the inner text right away, so we show a correct format on load
        document.getElementById('neuron-stake-root').innerHTML =
            formatNumber(calculatedStakeRoot, root_symbol_html);

        // Dividends, Incentive
        document.getElementById('neuron-dividends').setAttribute(
            'data-value', metagraphInfo.dividends[rowIndex]
        );
        document.getElementById('neuron-dividends').setAttribute('data-symbol', '');

        document.getElementById('neuron-incentive').setAttribute(
            'data-value', metagraphInfo.incentives[rowIndex]
        );
        document.getElementById('neuron-incentive').setAttribute('data-symbol', '');

        // Emissions
        document.getElementById('neuron-emissions').setAttribute(
            'data-value', metagraphInfo.emission[rowIndex]
        );
        document.getElementById('neuron-emissions').setAttribute('data-symbol', subnetSymbol);

        // Rank
        document.getElementById('neuron-rank').textContent = rank.toFixed(4);

        // Re-run formatting so the newly updated data-values appear in numeric form
        initializeFormattedNumbers();
    } catch (err) {
        console.error('Error showing neuron details:', err);
    }
}

/**
* Closes the neuron detail panel and goes back to whichever table was selected ("Stakes" or "Metagraph").
*/
function closeNeuronDetails() {
    // Hide neuron details
    const detailContainer = document.getElementById('neuron-detail-container');
    if (detailContainer) detailContainer.style.display = 'none';

    // Show the stakes header with action buttons
    const stakesHeader = document.querySelector('.stakes-header');
    if (stakesHeader) stakesHeader.style.display = 'flex';

    // Show the view header again
    const viewHeader = document.querySelector('.view-header');
    if (viewHeader) viewHeader.style.display = 'block';

    // Show the appropriate table based on toggle state
    const showStakes = document.getElementById('stake-toggle').checked;
    const stakesTable = document.querySelector('.stakes-table-container');
    const networkTable = document.querySelector('.network-table-container');

    if (showStakes) {
        stakesTable.style.display = 'block';
        networkTable.style.display = 'none';

        // Hide action buttons when showing stakes
        const addStakeButton = document.querySelector('.add-stake-button');
        const exportCsvButton = document.querySelector('.export-csv-button');
        if (addStakeButton) addStakeButton.style.display = 'none';
        if (exportCsvButton) exportCsvButton.style.display = 'none';
    } else {
        stakesTable.style.display = 'none';
        networkTable.style.display = 'block';

        // Show action buttons when showing metagraph
        const addStakeButton = document.querySelector('.add-stake-button');
        const exportCsvButton = document.querySelector('.export-csv-button');
        if (addStakeButton) addStakeButton.style.display = 'block';
        if (exportCsvButton) exportCsvButton.style.display = 'block';
    }
}


/* ===================== Number Formatting Functions ===================== */
/**
 * Toggles the numeric display between "verbose" and "short" notations
 * across all .formatted-number elements on the page.
 */
function toggleVerboseNumbers() {
    // We read from the main or subnet checkboxes
    verboseNumbers =
        document.getElementById('verbose-toggle')?.checked ||
        document.getElementById('show-verbose')?.checked ||
        false;

    // Reformat all visible .formatted-number elements
    document.querySelectorAll('.formatted-number').forEach(element => {
        const value = parseFloat(element.dataset.value);
        const symbol = element.dataset.symbol;
        element.innerHTML = formatNumber(value, symbol);
    });

    // If we're currently on the Subnet detail page, update those numbers too
    if (document.getElementById('subnet-page').style.display !== 'none') {
        updateAllNumbers();
    }
}

/**
 * Scans all .formatted-number elements and replaces their text with
 * the properly formatted version (short or verbose).
 */
function initializeFormattedNumbers() {
    document.querySelectorAll('.formatted-number').forEach(element => {
        const value = parseFloat(element.dataset.value);
        const symbol = element.dataset.symbol;
        element.innerHTML = formatNumber(value, symbol);
    });
}

/**
 * Called by toggleVerboseNumbers() to reformat key metrics on the Subnet page
 * that might not be directly wrapped in .formatted-number but need to be updated anyway.
 */
function updateAllNumbers() {
    try {
        const subnet = window.initialData.subnets.find(s => s.netuid === window.currentSubnet);
        if (!subnet) {
            console.error('Could not find subnet data for netuid:', window.currentSubnet);
            return;
        }
        // Reformat a few items in the Subnet detail header
        document.querySelector('#subnet-market-cap').innerHTML =
            formatNumber(subnet.market_cap, root_symbol_html);
        document.querySelector('#subnet-total-stake').innerHTML =
            formatNumber(subnet.total_stake, subnet.symbol);
        document.querySelector('#subnet-emission').innerHTML =
            formatNumber(subnet.emission, root_symbol_html);

        // Reformat the Metagraph table data
        const netinfo = subnet.metagraph_info;
        document.querySelector('#network-alpha-in').innerHTML =
            formatNumber(netinfo.alpha_in, subnet.symbol);
        document.querySelector('#network-tau-in').innerHTML =
            formatNumber(netinfo.tao_in, root_symbol_html);

        // Reformat items in "Your Stakes" table
        document.querySelectorAll('#stakes-table-body .formatted-number').forEach(element => {
            const value = parseFloat(element.dataset.value);
            const symbol = element.dataset.symbol;
            element.innerHTML = formatNumber(value, symbol);
        });
    } catch (error) {
        console.error('Error updating numbers:', error);
    }
}

/**
* Format a numeric value into either:
*  - a short format (e.g. 1.23k, 3.45m) if verboseNumbers==false
*  - a more precise format (1,234.5678) if verboseNumbers==true
* @param {number} num The numeric value to format.
* @param {string} symbol A short suffix or currency symbol (e.g. 'τ') that we append.
*/
function formatNumber(num, symbol = '') {
    if (num === undefined || num === null || isNaN(num)) {
        return '0.00 ' + `<span style="color: #FF9900">${symbol}</span>`;
    }
    num = parseFloat(num);
    if (num === 0) {
        return '0.00 ' + `<span style="color: #FF9900">${symbol}</span>`;
    }

    // If user requested verbose
    if (verboseNumbers) {
        return num.toLocaleString('en-US', {
            minimumFractionDigits: 4,
            maximumFractionDigits: 4
        }) + ' ' + `<span style="color: #FF9900">${symbol}</span>`;
    }

    // Otherwise show short scale for large numbers
    const absNum = Math.abs(num);
    if (absNum >= 1000) {
        const suffixes = ['', 'k', 'm', 'b', 't'];
        const magnitude = Math.min(4, Math.floor(Math.log10(absNum) / 3));
        const scaledNum = num / Math.pow(10, magnitude * 3);
        return scaledNum.toFixed(2) + suffixes[magnitude] + ' ' +
            `<span style="color: #FF9900">${symbol}</span>`;
    } else {
        // For small numbers <1000, just show 4 decimals
        return num.toFixed(4) + ' ' + `<span style="color: #FF9900">${symbol}</span>`;
    }
}

/**
* Truncates a string address into the format "ABC..XYZ" for a bit more readability
* @param {string} address
* @returns {string} truncated address form
*/
function truncateAddress(address) {
    if (!address || address.length <= 7) {
        return address; // no need to truncate if very short
    }
    return `${address.substring(0, 3)}..${address.substring(address.length - 3)}`;
}

/**
* Format a number in compact notation (K, M, B) for tile display
*/
function formatTileNumbers(num) {
    if (num >= 1000000000) {
        return (num / 1000000000).toFixed(1) + 'B';
    } else if (num >= 1000000) {
        return (num / 1000000).toFixed(1) + 'M';
    } else if (num >= 1000) {
        return (num / 1000).toFixed(1) + 'K';
    } else {
        return num.toFixed(1);
    }
}


/* ===================== Table Sorting and Filtering Functions ===================== */
/**
* Switches the Metagraph or Stakes table from sorting ascending to descending on a column, and vice versa.
* @param {HTMLTableElement} table The table element itself
* @param {number} columnIndex The column index to sort by
* @param {HTMLTableHeaderCellElement} header The <th> element clicked
* @param {boolean} forceDescending If true and no existing sort marker, will do a descending sort by default
*/
function sortTable(table, columnIndex, header, forceDescending = false) {
    const tbody = table.querySelector('tbody');
    const rows = Array.from(tbody.querySelectorAll('tr'));

    // If forcing descending and the header has no 'data-sort', default to 'desc'
    let isDescending;
    if (forceDescending && !header.hasAttribute('data-sort')) {
        isDescending = true;
    } else {
        isDescending = header.getAttribute('data-sort') !== 'desc';
    }

    // Clear data-sort from all headers in the table
    table.querySelectorAll('th').forEach(th => {
        th.removeAttribute('data-sort');
    });
    // Mark the clicked header with new direction
    header.setAttribute('data-sort', isDescending ? 'desc' : 'asc');

    // Sort numerically
    rows.sort((rowA, rowB) => {
        const cellA = rowA.cells[columnIndex];
        const cellB = rowB.cells[columnIndex];

        // Attempt to parse float from data-value or fallback to textContent
        let valueA = parseFloat(cellA.getAttribute('data-value')) ||
                    parseFloat(cellA.textContent.replace(/[^\\d.-]/g, '')) ||
                    0;
        let valueB = parseFloat(cellB.getAttribute('data-value')) ||
                    parseFloat(cellB.textContent.replace(/[^\\d.-]/g, '')) ||
                    0;

        return isDescending ? (valueB - valueA) : (valueA - valueB);
    });

    // Reinsert sorted rows
    tbody.innerHTML = '';
    rows.forEach(row => tbody.appendChild(row));
}

/**
* Adds sortable behavior to certain columns in the "stakes-table" or "network-table".
* Called after these tables are created in showSubnetPage().
*/
function initializeSorting() {
    const networkTable = document.querySelector('.network-table');
    if (networkTable) {
        initializeTableSorting(networkTable);
    }
    const stakesTable = document.querySelector('.stakes-table');
    if (stakesTable) {
        initializeTableSorting(stakesTable);
    }
}

/**
* Helper function that attaches sort handlers to appropriate columns in a table.
* @param {HTMLTableElement} table The table element to set up sorting for.
*/
function initializeTableSorting(table) {
    const headers = table.querySelectorAll('th');
    headers.forEach((header, index) => {
        // We only want some columns to be sortable, as in original code
        if (table.classList.contains('stakes-table') && index >= 1 && index <= 5) {
            header.classList.add('sortable');
            header.addEventListener('click', () => {
                sortTable(table, index, header, true);
            });
        } else if (table.classList.contains('network-table') && index < 6) {
            header.classList.add('sortable');
            header.addEventListener('click', () => {
                sortTable(table, index, header, true);
            });
        }
    });
}

/**
* Filters rows in the Metagraph table by name, hotkey, or coldkey.
* Invoked by the oninput event of the #network-search field.
* @param {string} searchValue The substring typed by the user.
*/
function filterNetworkTable(searchValue) {
    const searchTerm = searchValue.toLowerCase().trim();
    const rows = document.querySelectorAll('.network-table tbody tr');

    rows.forEach(row => {
        const nameCell = row.querySelector('.identity-cell');
        const hotkeyContainer = row.querySelector('.hotkey-container[data-full-address]');
        const coldkeyContainer = row.querySelectorAll('.hotkey-container[data-full-address]')[1];

        const name   = nameCell ? nameCell.textContent.toLowerCase() : '';
        const hotkey = hotkeyContainer ? hotkeyContainer.getAttribute('data-full-address').toLowerCase() : '';
        const coldkey= coldkeyContainer ? coldkeyContainer.getAttribute('data-full-address').toLowerCase() : '';

        const matches = (name.includes(searchTerm) || hotkey.includes(searchTerm) || coldkey.includes(searchTerm));
        row.style.display = matches ? '' : 'none';
    });
}


/* ===================== Network Visualization Functions ===================== */
/**
* Initializes the network visualization on the canvas element.
*/
function initNetworkVisualization() {
    try {
        const canvas = document.getElementById('network-canvas');
        if (!canvas) {
            console.error('Canvas element (#network-canvas) not found');
            return;
        }
        const ctx = canvas.getContext('2d');

        const subnet = window.initialData.subnets.find(s => s.netuid === window.currentSubnet);
        if (!subnet) {
            console.error('Could not find subnet data for netuid:', window.currentSubnet);
            return;
        }
        const numNeurons = subnet.metagraph_info.num_uids;
        const nodes = [];

        // Randomly place nodes, each with a small velocity
        for (let i = 0; i < numNeurons; i++) {
            nodes.push({
                x: Math.random() * canvas.width,
                y: Math.random() * canvas.height,
                radius: 2,
                vx: (Math.random() - 0.5) * 0.5,
                vy: (Math.random() - 0.5) * 0.5
            });
        }

        // Animation loop
        function animate() {
            ctx.clearRect(0, 0, canvas.width, canvas.height);

            ctx.beginPath();
            ctx.strokeStyle = 'rgba(255, 153, 0, 0.2)';
            for (let i = 0; i < nodes.length; i++) {
                for (let j = i + 1; j < nodes.length; j++) {
                    const dx = nodes[i].x - nodes[j].x;
                    const dy = nodes[i].y - nodes[j].y;
                    const distance = Math.sqrt(dx * dx + dy * dy);
                    if (distance < 30) {
                        ctx.moveTo(nodes[i].x, nodes[i].y);
                        ctx.lineTo(nodes[j].x, nodes[j].y);
                    }
                }
            }
            ctx.stroke();

            nodes.forEach(node => {
                node.x += node.vx;
                node.y += node.vy;

                // Bounce them off the edges
                if (node.x <= 0 || node.x >= canvas.width)  node.vx *= -1;
                if (node.y <= 0 || node.y >= canvas.height) node.vy *= -1;

                ctx.beginPath();
                ctx.fillStyle = '#FF9900';
                ctx.arc(node.x, node.y, node.radius, 0, Math.PI * 2);
                ctx.fill();
            });

            requestAnimationFrame(animate);
        }
        animate();
    } catch (error) {
        console.error('Error in network visualization:', error);
    }
}


/* ===================== Tile View Functions ===================== */
/**
* Toggles between the tile view and table view of subnets.
 */
function toggleTileView() {
    const showTiles = document.getElementById('show-tiles').checked;
    const tilesContainer = document.getElementById('subnet-tiles-container');
    const tableContainer = document.querySelector('.subnets-table-container');

    if (showTiles) {
        // Show tiles, hide table
        tilesContainer.style.display = 'flex';
        tableContainer.style.display = 'none';

        // Generate tiles if they don't exist yet
        if (tilesContainer.children.length === 0) {
            generateSubnetTiles();
        }

        // Apply current filters to the tiles
        filterSubnets();
    } else {
        // Show table, hide tiles
        tilesContainer.style.display = 'none';
        tableContainer.style.display = 'block';
    }
}

/**
* Generates the subnet tiles based on the initialData.
 */
function generateSubnetTiles() {
    const tilesContainer = document.getElementById('subnet-tiles-container');
    tilesContainer.innerHTML = ''; // Clear existing tiles

    // Sort subnets by market cap (descending)
    const sortedSubnets = [...window.initialData.subnets].sort((a, b) => b.market_cap - a.market_cap);

    sortedSubnets.forEach(subnet => {
        const isStaked = subnet.your_stakes && subnet.your_stakes.length > 0;
        const marketCapFormatted = formatTileNumbers(subnet.market_cap);

        const tile = document.createElement('div');
        tile.className = `subnet-tile ${isStaked ? 'staked' : ''}`;
        tile.onclick = () => showSubnetPage(subnet.netuid);

        // Calculate background intensity based on market cap relative to max
        const maxMarketCap = sortedSubnets[0].market_cap;
        const intensity = Math.max(5, Math.min(15, 5 + (subnet.market_cap / maxMarketCap) * 10));

        tile.innerHTML = `
            <span class="tile-netuid">${subnet.netuid}</span>
            <span class="tile-symbol">${subnet.symbol}</span>
            <span class="tile-name">${subnet.name}</span>
            <span class="tile-market-cap">${marketCapFormatted} ${root_symbol_html}</span>
        `;

        // Set background intensity
        tile.style.background = `rgba(255, 255, 255, 0.0${intensity.toFixed(0)})`;

        tilesContainer.appendChild(tile);
    });
}