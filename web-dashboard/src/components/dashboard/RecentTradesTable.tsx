import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useDashboardStore } from "@/store/dashboardStore";

export function RecentTradesTable(): React.JSX.Element {
  const executionTrail = useDashboardStore((state) => state.baseSnapshot.executionTrail);

  return (
    <Card className="border-cyan-500/15 bg-[#081014]/95">
      <CardHeader>
        <CardTitle>On-Chain Execution Trail</CardTitle>
      </CardHeader>
      <CardContent className="max-h-[420px] overflow-auto">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Time</TableHead>
              <TableHead>Pair</TableHead>
              <TableHead>Side</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Venue</TableHead>
              <TableHead className="text-right">Notional</TableHead>
              <TableHead>Tx Hash</TableHead>
              <TableHead>Note</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {executionTrail.map((trade) => (
              <TableRow key={trade.id} className="align-top">
                <TableCell className="font-mono text-xs text-zinc-400">
                  {new Date(trade.timestamp).toLocaleTimeString()}
                </TableCell>
                <TableCell>{trade.pair}</TableCell>
                <TableCell>
                  <Badge variant={trade.side === "BUY" ? "default" : trade.side === "SELL" ? "danger" : "muted"}>
                    {trade.side}
                  </Badge>
                </TableCell>
                <TableCell>
                  <Badge variant={trade.status === "Timeout" || trade.status === "Failed" ? "danger" : "muted"}>
                    {trade.status}
                  </Badge>
                </TableCell>
                <TableCell className="text-zinc-300">{trade.venue}</TableCell>
                <TableCell className="text-right font-mono">${trade.notionalUsd.toFixed(2)}</TableCell>
                <TableCell className="max-w-48 truncate font-mono text-xs text-cyan-200">{trade.txHash}</TableCell>
                <TableCell className="max-w-80 text-zinc-300">{trade.note}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  );
}
