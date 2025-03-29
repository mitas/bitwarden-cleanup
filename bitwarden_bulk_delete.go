package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"os/exec"
	"strings"
	"sync"
)

type BitwardenItem struct {
	ID   string `json:"id"`
	Name string `json:"name"`
}

type CommandOptions struct {
	searchTerm  string
	batchSize   int
	isPermanent bool
}

type DeleteStats struct {
	total     int
	completed int
}

// UI emojis
const (
	emojiError      = "❌"
	emojiSuccess    = "✅"
	emojiSync       = "🔄"
	emojiSearch     = "🔍"
	emojiWarning    = "⚠️"
	emojiInfo       = "ℹ️"
	emojiStart      = "🚀"
	emojiProgress   = "⏳"
	emojiComplete   = "🎉"
)

func main() {
	options := parseCommandLineOptions()

	if err := runBulkDelete(options); err != nil {
		fmt.Printf("%s Error: %v\n", emojiError, err)
		os.Exit(1)
	}
}

func parseCommandLineOptions() CommandOptions {
	searchTerm := flag.String("search", "", "Search term to filter items")
	searchShort := flag.String("s", "", "Search term to filter items (shorthand)")
	batchSize := flag.Int("batch", 1, "Number of items to process in parallel")
	batchShort := flag.Int("b", 1, "Number of items to process in parallel (shorthand)")
	permanent := flag.Bool("permanent", false, "Permanently delete items (skip trash)")
	permanentShort := flag.Bool("p", false, "Permanently delete items (skip trash) (shorthand)")
	
	flag.Parse()

	options := CommandOptions{}
	
	options.searchTerm = *searchTerm
	if options.searchTerm == "" && *searchShort != "" {
		options.searchTerm = *searchShort
	}

	options.batchSize = *batchSize
	if *batchSize == 1 && *batchShort != 1 {
		options.batchSize = *batchShort
	}
	
	options.isPermanent = *permanent || *permanentShort

	return options
}

func runBulkDelete(options CommandOptions) error {
	if err := checkBitwardenCLI(); err != nil {
		return err
	}
	
	displayDeletionMode(options)

	if err := syncBitwarden("before starting"); err != nil {
		fmt.Printf("%s Warning: Initial sync failed but continuing\n", emojiWarning)
	}

	items, err := fetchBitwardenItems(options.searchTerm)
	if err != nil {
		return err
	}

	stats := &DeleteStats{total: len(items)}
	displayItemCount(stats)

	if stats.total > 0 {
		if confirmed := confirmDeletion(stats, options); !confirmed {
			fmt.Printf("%s Operation cancelled\n", emojiError)
			return nil
		}

		if err := processItems(items, stats, options); err != nil {
			return err
		}

		if err := syncBitwarden(""); err != nil {
			fmt.Printf("%s Warning: Final sync failed\n", emojiWarning)
		}
	}

	return nil
}

func checkBitwardenCLI() error {
	if _, err := exec.LookPath("bw"); err != nil {
		return fmt.Errorf("Bitwarden CLI (bw) not found in PATH. Please install it first: %w", err)
	}
	return nil
}

func syncBitwarden(context string) error {
	contextMsg := ""
	if context != "" {
		contextMsg = " " + context
	}
	fmt.Printf("%s Syncing Bitwarden database%s...\n", emojiSync, contextMsg)
	
	syncCmd := exec.Command("bw", "sync")
	syncOutput, err := syncCmd.CombinedOutput()
	
	if err != nil {
		fmt.Printf("%s Failed to sync Bitwarden: %v\n", emojiError, err)
		fmt.Printf("%s Command output: %s\n", emojiError, string(syncOutput))
		return err
	} 
	
	fmt.Printf("%s Sync completed successfully\n", emojiSuccess)
	fmt.Printf("%s Command output: %s\n", emojiSuccess, string(syncOutput))
	return nil
}

func fetchBitwardenItems(searchTerm string) ([]BitwardenItem, error) {
	fmt.Printf("%s Fetching Bitwarden items...\n", emojiSearch)
	
	listCmd := "bw list items"
	if searchTerm != "" {
		listCmd += fmt.Sprintf(" --search '%s'", searchTerm)
	}
	
	listCommand := exec.Command("sh", "-c", listCmd)
	listOutput, err := listCommand.Output()
	if err != nil {
		return nil, fmt.Errorf("error executing list command: %w", err)
	}

	var items []BitwardenItem
	if err := json.Unmarshal(listOutput, &items); err != nil {
		return nil, fmt.Errorf("error parsing list output: %w", err)
	}
	
	return items, nil
}

func displayDeletionMode(options CommandOptions) {
	if options.isPermanent {
		fmt.Printf("%s Mode: Permanent deletion (items will bypass trash)\n", emojiWarning)
	} else {
		fmt.Printf("%s Mode: Standard deletion (items will go to trash)\n", emojiInfo)
	}
}

func displayItemCount(stats *DeleteStats) {
	fmt.Printf("%s Found %d items to delete\n", emojiSearch, stats.total)
}

func confirmDeletion(stats *DeleteStats, options CommandOptions) bool {
	confirmMsg := "Are you sure you want to delete all"
	if options.isPermanent {
		confirmMsg = "Are you sure you want to PERMANENTLY delete all"
	}
	
	fmt.Printf("%s %s %d items? (y/N) ", emojiWarning, confirmMsg, stats.total)
	var confirm string
	if _, err := fmt.Scanln(&confirm); err != nil {
		fmt.Printf("%s Error reading confirmation: %v\n", emojiError, err)
		return false
	}

	confirm = strings.ToLower(confirm)
	return confirm == "y" || confirm == "yes"
}

func processItems(items []BitwardenItem, stats *DeleteStats, options CommandOptions) error {
	fmt.Printf("%s Starting deletion process...\n", emojiStart)

	jobs := make(chan string, stats.total)
	results := make(chan string, stats.total)
	var wg sync.WaitGroup

	for w := 1; w <= options.batchSize; w++ {
		wg.Add(1)
		go deleteWorker(w, jobs, results, &wg, options.isPermanent)
	}

	for _, item := range items {
		jobs <- item.ID
	}
	close(jobs)

	go func() {
		wg.Wait()
		close(results)
	}()

	processResults(results, stats)
	showCompletionMessage(stats, options)
	
	return nil
}

func deleteWorker(id int, jobs <-chan string, results chan<- string, wg *sync.WaitGroup, isPermanent bool) {
	defer wg.Done()
	for itemID := range jobs {
		var deleteCmd *exec.Cmd
		
		if isPermanent {
			deleteCmd = exec.Command("bw", "delete", "item", itemID, "--permanent")
		} else {
			deleteCmd = exec.Command("bw", "delete", "item", itemID)
		}
		
		if err := deleteCmd.Run(); err != nil {
			fmt.Printf("%s Error deleting item %s: %v\n", emojiError, itemID, err)
		}
		results <- itemID
	}
}

func processResults(results <-chan string, stats *DeleteStats) {
	for range results {
		stats.completed++
		fmt.Printf("%s Progress: [%d/%d]\r", emojiProgress, stats.completed, stats.total)
	}
	fmt.Println()
}

func showCompletionMessage(stats *DeleteStats, options CommandOptions) {
	if options.isPermanent {
		fmt.Printf("%s All %d items have been permanently deleted!\n", emojiComplete, stats.total)
	} else {
		fmt.Printf("%s All %d items have been moved to trash!\n", emojiComplete, stats.total)
	}
}