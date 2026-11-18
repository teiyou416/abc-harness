package simblock.settings;

// Trimmed copy of the upstream file: only the lines the harness edits, plus
// the commented-out duplicates that the patterns must leave alone.
public class SimulationConfiguration {
  public static final int NUM_OF_NODES = 300; // 600;//800;//6000;
  // public static final int NUM_OF_NODES = 600;//600;//800;//6000;
  public static final long INTERVAL = 1000 * 60 * 10; // 1000*60;//1000*30*5;//1000*60*10;
  public static final long AVERAGE_MINING_POWER = 400000;
  public static final long STDEV_OF_MINING_POWER = 100000;
  // public static final int END_BLOCK_HEIGHT = 100;
  public static final int END_BLOCK_HEIGHT = 3;
  public static final long BLOCK_SIZE = 535000; // 6110;//8000;//535000;//0.5MB
  public static final float CBR_USAGE_RATE = 0.964f;
  public static final float CHURN_NODE_RATE = 0.976f;
}
